"""
PostgreSQL bilan ishlash — asyncpg orqali async CRUD operatsiyalar.

NIMA QILADI:
- PostgreSQL bazaga CONNECTION POOL orqali ulanadi
- 4 ta jadval bilan ishlaydi: connections, chats, messages, bot_users
- Har bir xabarni bazaga yozadi, connectionlarni saqlaydi

NEGA POOL (SQLite dan asosiy farq):
- SQLite da bitta ulanish bor edi — barcha yozuvlar navbatda kutardi (bitta yozuvchi).
- PostgreSQL da POOL bor: bir nechta ulanish parallel ishlaydi.
  Aktiv userlar ostida bir vaqtda bir nechta yozuv/o'qish bajariladi.
- pool.execute()/fetch() avtomatik ulanish oladi va qaytaradi.

QANDAY ISHLAYDI:
- Database sinfi — singleton (bitta global obyekt: db)
- connect(dsn) — poolni yaratadi, migratsiyalarni (jadval yaratish) bajaradi
- close() — poolni yopadi (bot to'xtayotganda)
- upsert_connection() / upsert_chat() / insert_message() / mark_* / *_bot_user()

XATO BO'LSA:
- Har bir operatsiya try/except bilan o'ralgan
- Xato bo'lsa: log qilinadi, lekin bot TO'XTAMAYDI — davom etadi

SQLITE DAN FARQLAR (kod ichida):
- ? placeholder  -> $1, $2, ...
- datetime('now') -> now()
- 0/1 (boolean)   -> haqiqiy bool (True/False/None)
- raw_json string -> $N::jsonb (JSONB ustunga cast)
- lastrowid       -> RETURNING id + fetchval
- IN (?,?,?)      -> = ANY($3::bigint[])
- tg_date isoformat string YO'Q — datetime obyekti to'g'ridan-to'g'ri beriladi
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

import asyncpg  # PostgreSQL uchun async driver

logger = logging.getLogger("bot.db")


class Database:
    """
    PostgreSQL baza bilan ishlash uchun async wrapper (connection pool).

    Ishlatish:
        db = Database()
        await db.connect("postgresql://user:pass@host:5432/dbname")  # startup
        await db.insert_message(...)                                  # xabar kelganda
        await db.close()                                              # shutdown
    """

    def __init__(self) -> None:
        self._dsn: str = ""
        self._pool: Optional[asyncpg.Pool] = None  # ulanishlar puli

    async def connect(
        self,
        dsn: str,
        min_size: int = 2,
        max_size: int = 10,
    ) -> None:
        """
        PostgreSQL bazaga connection pool orqali ulanadi va migratsiyalarni bajaradi.

        dsn — ulanish satri, masalan:
              postgresql://user:password@localhost:5432/botdb
        min_size / max_size — pooldagi ulanishlar soni (parallel yozuv sig'imi).
        """
        self._dsn = dsn

        # Connection pool yaratish — bir nechta ulanish parallel ishlaydi
        self._pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=30,  # bitta so'rov 30s dan oshsa — xato (osilib qolmaslik uchun)
        )

        logger.info("PostgreSQL pool connected (min=%d, max=%d)", min_size, max_size)

        # Jadvallarni yaratish (agar yo'q bo'lsa)
        await self._run_migrations()

    async def close(self) -> None:
        """Poolni yopadi — bot to'xtayotganda chaqiriladi."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL pool closed")

    async def _run_migrations(self) -> None:
        """
        migrations/002_init_postgres.sql faylini o'qib bajaradi.

        Fayl jadvallarni CREATE TABLE IF NOT EXISTS bilan yaratadi —
        allaqachon mavjud bo'lsa qayta yaratmaydi (xavfsiz, har startupda chaqirsa bo'ladi).
        """
        migration_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),  # app/ -> bot/
            "migrations",
            "002_init_postgres.sql",
        )

        if not os.path.exists(migration_file):
            logger.warning("Migration file not found: %s", migration_file)
            return

        with open(migration_file, "r", encoding="utf-8") as f:
            sql = f.read()

        # asyncpg: argumentsiz execute bir nechta SQL buyruqni birdan bajaradi
        async with self._pool.acquire() as conn:
            await conn.execute(sql)
        logger.info("Migrations applied successfully")

    # ===================================================================
    # CONNECTIONS JADVALI — botni ulagan xodimlar
    # ===================================================================

    async def upsert_connection(
        self,
        connection_id: str,
        user_id: int,
        user_chat_id: Optional[int],
        username: Optional[str],
        first_name: Optional[str],
        can_reply: Optional[bool],
        is_enabled: bool,
    ) -> None:
        """
        Connection yaratadi yoki yangilaydi (upsert = INSERT + UPDATE).
        ON CONFLICT (id) DO UPDATE — id mavjud bo'lsa yangilaydi.
        """
        try:
            await self._pool.execute(
                """
                INSERT INTO connections
                    (id, user_id, user_chat_id, username, first_name,
                     can_reply, is_enabled, connected_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, now(), now())
                ON CONFLICT (id) DO UPDATE SET
                    user_id      = EXCLUDED.user_id,
                    user_chat_id = EXCLUDED.user_chat_id,
                    username     = EXCLUDED.username,
                    first_name   = EXCLUDED.first_name,
                    can_reply    = EXCLUDED.can_reply,
                    is_enabled   = EXCLUDED.is_enabled,
                    updated_at   = now()
                """,
                connection_id,
                user_id,
                user_chat_id,
                username,
                first_name,
                can_reply,   # bool | None — Postgres BOOLEAN
                is_enabled,  # bool
            )
            logger.info(
                "Connection upserted: %s (user_id=%d, enabled=%s)",
                connection_id,
                user_id,
                is_enabled,
            )
        except Exception:
            logger.error(
                "Failed to upsert connection %s", connection_id, exc_info=True
            )

    # ===================================================================
    # CHATS JADVALI — kashf qilingan chatlar
    # ===================================================================

    async def upsert_chat(
        self,
        connection_id: str,
        chat_id: int,
        chat_type: Optional[str],
        title: Optional[str],
        username: Optional[str],
    ) -> None:
        """
        Chatni yaratadi yoki last_message_at va message_count ni yangilaydi.
        """
        try:
            await self._pool.execute(
                """
                INSERT INTO chats
                    (connection_id, chat_id, chat_type, title, username,
                     first_seen, last_message_at, message_count)
                VALUES ($1, $2, $3, $4, $5, now(), now(), 1)
                ON CONFLICT (connection_id, chat_id) DO UPDATE SET
                    chat_type       = COALESCE(EXCLUDED.chat_type, chats.chat_type),
                    title           = COALESCE(EXCLUDED.title, chats.title),
                    username        = COALESCE(EXCLUDED.username, chats.username),
                    last_message_at = now(),
                    message_count   = chats.message_count + 1
                """,
                connection_id,
                chat_id,
                chat_type,
                title,
                username,
            )
        except Exception:
            logger.error(
                "Failed to upsert chat conn=%s chat=%d",
                connection_id,
                chat_id,
                exc_info=True,
            )

    # ===================================================================
    # MESSAGES JADVALI — hamma xabarlar
    # ===================================================================

    async def insert_message(
        self,
        connection_id: Optional[str],
        chat_id: int,
        from_user_id: Optional[int],
        from_user_name: Optional[str],
        message_id: int,
        direction: str,
        content_type: str,
        text: Optional[str],
        media_file_id: Optional[str],
        media_file_name: Optional[str],
        media_mime: Optional[str],
        media_duration: Optional[int],
        is_edited: bool,
        raw_json: dict[str, Any],
        tg_date: Optional[datetime],
    ) -> Optional[int]:
        """
        Xabarni bazaga yozadi.

        Qaytaradi: yangi qatorning id raqami yoki None (xato bo'lsa).
        raw_json — JSONB ustunga saqlanadi ($14::jsonb cast bilan).
        tg_date — datetime obyekti to'g'ridan-to'g'ri TIMESTAMPTZ ga yoziladi.
        """
        try:
            # dict -> JSON string (JSONB ustunga cast qilinadi)
            raw_json_str = json.dumps(raw_json, ensure_ascii=False, default=str)

            new_id = await self._pool.fetchval(
                """
                INSERT INTO messages
                    (connection_id, chat_id, from_user_id, from_user_name,
                     message_id, direction, content_type, text,
                     media_file_id, media_file_name, media_mime,
                     media_duration, is_edited, raw_json, tg_date)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,$15)
                RETURNING id
                """,
                connection_id,
                chat_id,
                from_user_id,
                from_user_name,
                message_id,
                direction,
                content_type,
                text,
                media_file_id,
                media_file_name,
                media_mime,
                media_duration,
                is_edited,      # bool
                raw_json_str,   # ::jsonb ga cast bo'ladi
                tg_date,        # datetime | None
            )
            return new_id
        except Exception:
            logger.error(
                "Failed to insert message (conn=%s, chat=%s, msg_id=%s)",
                connection_id,
                chat_id,
                message_id,
                exc_info=True,
            )
            return None

    async def mark_edited(
        self,
        connection_id: str,
        chat_id: int,
        message_id: int,
    ) -> None:
        """Mavjud xabarni is_edited=TRUE qilib belgilaydi."""
        try:
            await self._pool.execute(
                """
                UPDATE messages
                SET is_edited = TRUE
                WHERE connection_id = $1
                  AND chat_id = $2
                  AND message_id = $3
                """,
                connection_id,
                chat_id,
                message_id,
            )
        except Exception:
            logger.error(
                "Failed to mark edited (conn=%s, chat=%d, msg_id=%d)",
                connection_id,
                chat_id,
                message_id,
                exc_info=True,
            )

    async def mark_deleted(
        self,
        connection_id: str,
        chat_id: int,
        message_ids: list[int],
    ) -> None:
        """
        Berilgan message_id larni is_deleted=TRUE qilib belgilaydi.
        Xabar bazadan O'CHIRILMAYDI — tarix saqlanadi.
        """
        if not message_ids:
            return
        try:
            # SQLite dagi IN (?,?,?) o'rniga Postgres da = ANY(massiv) — toza va tez
            await self._pool.execute(
                """
                UPDATE messages
                SET is_deleted = TRUE
                WHERE connection_id = $1
                  AND chat_id = $2
                  AND message_id = ANY($3::bigint[])
                """,
                connection_id,
                chat_id,
                message_ids,
            )
            logger.info(
                "Marked %d messages as deleted (conn=%s, chat=%d)",
                len(message_ids),
                connection_id,
                chat_id,
            )
        except Exception:
            logger.error(
                "Failed to mark deleted (conn=%s, chat=%d)",
                connection_id,
                chat_id,
                exc_info=True,
            )

    # ===================================================================
    # BOT USERS JADVALI — /start bosgan oddiy foydalanuvchilar
    # ===================================================================

    async def upsert_bot_user(
        self,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        language_code: Optional[str],
    ) -> None:
        """Foydalanuvchini bazaga qo'shadi (yoki ma'lumotlarini yangilaydi)."""
        try:
            await self._pool.execute(
                """
                INSERT INTO bot_users
                    (user_id, username, first_name, last_name, language_code, created_at)
                VALUES ($1, $2, $3, $4, $5, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    language_code = EXCLUDED.language_code
                """,
                user_id,
                username,
                first_name,
                last_name,
                language_code,
            )
            logger.info("Upserted bot_user %d", user_id)
        except Exception:
            logger.error("Failed to upsert bot_user %d", user_id, exc_info=True)

    async def get_all_bot_users(self) -> list[int]:
        """Barcha bot foydalanuvchilarining user_id ro'yxatini qaytaradi."""
        try:
            rows = await self._pool.fetch("SELECT user_id FROM bot_users")
            return [row["user_id"] for row in rows]
        except Exception:
            logger.error("Failed to get bot users", exc_info=True)
            return []

    # ===================================================================
    # TAHRIR / O'CHIRISH bildirishnomalari uchun O'QISH metodlari
    # ===================================================================

    async def get_last_message(
        self,
        connection_id: str,
        chat_id: int,
        message_id: int,
    ) -> Optional[dict[str, Any]]:
        """
        Shu Telegram message_id ning bazadagi ENG OXIRGI versiyasini qaytaradi.

        Tahrirlashda ishlatiladi: yangi versiya yozilishidan OLDIN chaqirilsa —
        "eski" (tahrirdan avvalgi) matnni beradi.
        """
        try:
            row = await self._pool.fetchrow(
                """
                SELECT from_user_id, from_user_name, direction, content_type, text, tg_date
                FROM messages
                WHERE connection_id = $1 AND chat_id = $2 AND message_id = $3
                ORDER BY id DESC
                LIMIT 1
                """,
                connection_id,
                chat_id,
                message_id,
            )
            return dict(row) if row else None
        except Exception:
            logger.error(
                "Failed to get last message (conn=%s, chat=%d, msg_id=%d)",
                connection_id,
                chat_id,
                message_id,
                exc_info=True,
            )
            return None

    async def get_messages_by_ids(
        self,
        connection_id: str,
        chat_id: int,
        message_ids: list[int],
    ) -> list[dict[str, Any]]:
        """
        Berilgan message_id lar uchun bazadagi ENG OXIRGI versiyalarni qaytaradi.

        O'chirish bildirishnomasida ishlatiladi: Telegram o'chirilgan xabar
        MATNINI bermaydi — shuning uchun bazadan tiklaymiz.
        Har message_id uchun eng oxirgi qator (DISTINCT ON).
        """
        if not message_ids:
            return []
        try:
            rows = await self._pool.fetch(
                """
                SELECT DISTINCT ON (message_id)
                       message_id, from_user_id, from_user_name,
                       direction, content_type, text, tg_date,
                       media_file_id, media_file_name,
                       raw_json #>> '{from,username}'   AS from_username,
                       raw_json #>> '{from,first_name}' AS from_first_name
                FROM messages
                WHERE connection_id = $1 AND chat_id = $2
                  AND message_id = ANY($3::bigint[])
                ORDER BY message_id, id DESC
                """,
                connection_id,
                chat_id,
                message_ids,
            )
            return [dict(r) for r in rows]
        except Exception:
            logger.error(
                "Failed to get messages by ids (conn=%s, chat=%d)",
                connection_id,
                chat_id,
                exc_info=True,
            )
            return []


# Global singleton — boshqa fayllar:
# from app.db import db
# await db.insert_message(...)
db = Database()
