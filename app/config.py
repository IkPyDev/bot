"""
Konfiguratsiya moduli — .env fayldan sozlamalarni o'qiydi.

NIMA QILADI:
- .env faylni topib, undagi qiymatlarni os.environ ga yuklaydi
- BOT_TOKEN (majburiy), DATABASE_PATH, LOG_LEVEL, LOG_FILE ni o'qiydi
- Settings dataclass yaratadi — dastur davomida o'zgarmas (frozen=True)

QANDAY ISHLAYDI:
- load_dotenv() — .env faylni topib, undagi KEY=VALUE larni muhit o'zgaruvchilariga yuklaydi
- Settings.from_env() — muhit o'zgaruvchilaridan qiymatlarni o'qib, Settings obyekt qaytaradi
- settings = Settings.from_env() — modul import qilinganda avtomatik yaratiladi (singleton)

O'ZGARTIRISH KERAK BO'LSA:
- Yangi sozlama qo'shish: Settings ga yangi maydon qo'sh + from_env() da os.getenv() qo'sh
- .env.example faylni ham yangilab qo'y
"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv  # .env faylni o'qib, muhit o'zgaruvchilariga yuklaydi

# .env faylni yuklash — bu fayl import qilinganida avtomatik ishlaydi
load_dotenv(override=True)


@dataclass(frozen=True)  # frozen=True — yaratilgandan keyin o'zgartib bo'lmaydi
class Settings:
    """Dastur sozlamalari. Barcha qiymatlar .env fayldan keladi."""

    bot_token: str        # Telegram bot tokeni (@BotFather dan olinadi)
    database_url: str     # PostgreSQL DSN (postgresql://user:pass@host:5432/db)
    log_level: str        # Log darajasi: DEBUG, INFO, WARNING, ERROR
    log_file: str         # Log fayl yo'li (masalan: logs/bot.log)
    admin_ids: list[int]  # Adminlarning Telegram ID lari (reklama yuborish uchun)
    channel_id: Optional[int]  # Xabarlar nusxasi yuboriladigan kanal ID si
    backup_channel_id: Optional[int]  # Kunlik log + DB backup yuboriladigan kanal
    backup_time: str      # Kunlik backup vaqti "HH:MM" (mahalliy vaqt), default "00:30"
    media_channel_id: Optional[int]          # Media (rasm/video) turgan "database" kanal ID
    start_media_message_id: Optional[int]    # /start uchun rasm/video xabar ID si
    connect_media_message_id: Optional[int]  # Ulanish (connection) uchun video xabar ID si
    android_media_message_id: Optional[int]  # "Android ulash" qo'llanma videosi xabar ID si
    ios_media_message_id: Optional[int]      # "iOS ulash" qo'llanma videosi xabar ID si

    @classmethod
    def from_env(cls) -> "Settings":
        """Muhit o'zgaruvchilaridan Settings yaratadi."""

        # BOT_TOKEN — majburiy, bo'lmasa dastur ishlamaydi
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise ValueError("BOT_TOKEN environment variable is required")

        # DATABASE_URL — PostgreSQL ulanish satri (majburiy)
        # Masalan: postgresql://user:password@localhost:5432/botdb
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")

        # LOG_LEVEL — ixtiyoriy, default: INFO
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        # LOG_FILE — ixtiyoriy, default: logs/bot.log
        log_file = os.getenv("LOG_FILE", "logs/bot.log")

        # ADMIN_IDS — vergul bilan ajratilgan ID lar
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        admin_ids = []
        if admin_ids_str:
            try:
                admin_ids = [int(i.strip()) for i in admin_ids_str.split(",") if i.strip()]
            except ValueError:
                pass

        # CHANNEL_ID — ixtiyoriy, xabarlar nusxasi yuboriladigan kanal
        channel_id_str = os.getenv("CHANNEL_ID", "")
        channel_id = None
        if channel_id_str.strip():
            try:
                channel_id = int(channel_id_str.strip())
            except ValueError:
                pass

        # BACKUP_CHANNEL_ID — kunlik log + DB backup shu kanalga boradi.
        # Sozlanmasa CHANNEL_ID ga tushadi (xabar nusxalari kanaliga aralashadi).
        backup_channel_id = None
        backup_channel_id_str = os.getenv("BACKUP_CHANNEL_ID", "")
        if backup_channel_id_str.strip():
            try:
                backup_channel_id = int(backup_channel_id_str.strip())
            except ValueError:
                pass
        if backup_channel_id is None:
            backup_channel_id = channel_id

        # BACKUP_TIME — kunlik backup vaqti "HH:MM" (mahalliy), default 00:30
        backup_time = os.getenv("BACKUP_TIME", "00:30").strip() or "00:30"

        # MEDIA_* — /start va ulanish media'si "database" kanalida turadi.
        # Bot o'sha kanaldan copy_message bilan olib, caption qo'shib yuboradi.
        def _to_int(name: str) -> Optional[int]:
            raw = os.getenv(name, "").strip()
            if not raw:
                return None
            try:
                return int(raw)
            except ValueError:
                return None

        media_channel_id = _to_int("MEDIA_CHANNEL_ID")
        start_media_message_id = _to_int("START_MEDIA_MESSAGE_ID")
        connect_media_message_id = _to_int("CONNECT_MEDIA_MESSAGE_ID")


        # "Android ulash" / "iOS ulash" tugmalari uchun alohida qo'llanma videolar.
        # Sozlanmasa — /start dagi video ishlatiladi (default), keyin .env da almashtiriladi.
        android_media_message_id = _to_int("ANDROID_MEDIA_MESSAGE_ID")
        if android_media_message_id is None:
            android_media_message_id = start_media_message_id

        ios_media_message_id = _to_int("IOS_MEDIA_MESSAGE_ID")
        if ios_media_message_id is None:
            ios_media_message_id = start_media_message_id

        return cls(
            bot_token=bot_token,
            database_url=database_url,
            log_level=log_level,
            log_file=log_file,
            admin_ids=admin_ids,
            channel_id=channel_id,
            backup_channel_id=backup_channel_id,
            backup_time=backup_time,
            media_channel_id=media_channel_id,
            start_media_message_id=start_media_message_id,
            connect_media_message_id=connect_media_message_id,
            android_media_message_id=android_media_message_id,
            ios_media_message_id=ios_media_message_id,
        )


# Dastur boshlanishida avtomatik yaratiladi — boshqa fayllar:
# from app.config import settings
# settings.bot_token, settings.database_path, va h.k. ishlatadi
settings = Settings.from_env()
