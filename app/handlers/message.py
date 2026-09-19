"""
business_message handler — ENG MUHIM QISM.

Har bir xabar uchun:
1. Umumiy maydonlar ajratiladi.
2. content_type aniqlanadi (12 tur).
3. Turga xos maydonlar ajratiladi.
4. direction aniqlanadi (incoming/outgoing).
5. Bazaga yoziladi (messages + chats).
6. To'liq logga chiqariladi.

Bot hech kimga javob YOZMAYDI.
"""

import asyncio
import html
import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message, MessageEntity
from aiogram.utils.text_decorations import html_decoration

from app.config import settings
from app.db import db
from app.extractors import (
    detect_content_type,
    determine_direction,
    extract_media_fields,
    extract_text_or_caption,
    special_content,
)
from app.handlers.connection import (
    connection_owner_users,
    connection_owners,
    connection_user_chats,
)
from app.i18n import pick_lang, t

router = Router(name="message")
logger = logging.getLogger("bot.handlers.message")


def owner_lang(connection_id: Optional[str]) -> str:
    """Connection egasining (owner) tili — keshdagi language_code bo'yicha.

    Topilmasa yoki qo'llab-quvvatlanmasa — inglizchaga tushadi (app/i18n.py).
    Owner'ga yuboriladigan bildirishnomalarni o'z tilida berish uchun ishlatiladi.
    """
    owner = connection_owner_users.get(connection_id) if connection_id else None
    lang_code = owner.get("language_code") if owner else None
    return pick_lang(lang_code)


# ============================================================
# MEDIA YUKLASH SEMAFORI
#
# Protected media to'liq RAM ga yuklab, qayta upload qilinadi.
# Bir vaqtda cheksiz yuklash = RAM/trafik portlashi. Semafor bilan
# bir vaqtda faqat N ta parallel yuklashga ruxsat beramiz.
# Loop bilan bog'lanish muammosi bo'lmasligi uchun — ishlab turgan
# loop ichida (birinchi chaqiruvda) yaratamiz.
# ============================================================

_MAX_PARALLEL_DOWNLOADS = 5
_download_semaphore: Optional[asyncio.Semaphore] = None


def _get_download_semaphore() -> asyncio.Semaphore:
    """Ishlab turgan loop ichida semaforni bir marta yaratadi (3.9 uchun xavfsiz)."""
    global _download_semaphore
    if _download_semaphore is None:
        _download_semaphore = asyncio.Semaphore(_MAX_PARALLEL_DOWNLOADS)
    return _download_semaphore


def user_link_html(
    name: Optional[str],
    username: Optional[str],
    user_id: Optional[int],
) -> str:
    """
    Ustiga bosilganda Telegram profiliga o'tadigan HTML havola qaytaradi.

    - username bo'lsa  -> https://t.me/username (ochiq profil)
    - bo'lmasa, id bor -> tg://user?id=<id> (ichki mention, profilga o'tadi)
    - ikkalasi ham yo'q -> oddiy (escape qilingan) matn

    Ism (label) HTML-escape qilinadi. parse_mode="HTML" bilan yuborilishi shart.
    """
    label = html.escape(name or "Noma'lum")
    if username:
        uname = username.lstrip("@")
        return f'<a href="https://t.me/{uname}">{label}</a>'
    if user_id:
        return f'<a href="tg://user?id={user_id}">{label}</a>'
    return label


def full_user_html(
    name: Optional[str],
    username: Optional[str],
    user_id: Optional[int],
) -> str:
    """
    Bosiladigan ism (tg://user?id=) + YONIDA ko'rinadigan @username va [ID].

    Masalan:  <a href="tg://user?id=123">Ali</a> @ali123 [ID: 123]
    Ustiga bosilsa profil ochiladi. parse_mode="HTML" bilan yuboriladi.
    """
    label = html.escape(name or "Noma'lum")
    if user_id:
        linked = f'<a href="tg://user?id={user_id}">{label}</a>'
    elif username:
        linked = f'<a href="https://t.me/{html.escape(username.lstrip("@"))}">{label}</a>'
    else:
        linked = label
    extras = []
    if username:
        extras.append(f"@{html.escape(username.lstrip('@'))}")
    if user_id:
        extras.append(f"[ID: {user_id}]")
    return linked + ((" " + " ".join(extras)) if extras else "")


def owner_link_html(connection_id: Optional[str]) -> Optional[str]:
    """Connection egasining (owner) to'liq havolasi (nom+@username+ID, keshdan)."""
    if not connection_id:
        return None
    owner = connection_owner_users.get(connection_id)
    if owner:
        name = " ".join(
            p for p in [owner.get("first_name") or "", owner.get("last_name") or ""] if p
        ) or None
        return full_user_html(name, owner.get("username"), owner.get("id"))
    oid = connection_owners.get(connection_id)
    if oid:
        return full_user_html(None, None, oid)
    return None


def chat_link_html(chat) -> str:
    """Chat (suhbatdosh/mijoz) ning to'liq havolasi (nom+@username+ID)."""
    if not chat:
        return "?"
    name = getattr(chat, "title", None)
    if not name:
        name = " ".join(
            p for p in [getattr(chat, "first_name", None), getattr(chat, "last_name", None)] if p
        )
    return full_user_html(name or None, getattr(chat, "username", None), getattr(chat, "id", None))


def format_chat_label(chat) -> str:
    """Chat yorlig'i (to'liq): 'Nomi @username [ID: 123]'."""
    if not chat:
        return "?"
    name = getattr(chat, "title", None)
    if not name:
        name = " ".join(
            p for p in [getattr(chat, "first_name", None), getattr(chat, "last_name", None)] if p
        )
    parts = []
    if name:
        parts.append(name)
    if getattr(chat, "username", None):
        parts.append(f"@{chat.username}")
    parts.append(f"[ID: {chat.id}]")
    return " ".join(parts).strip()


# ============================================================
# KANALGA FORWARD NAVBATI (fon worker)
#
# Har xabarni TO'G'RIDAN kanalga yuborish o'rniga navbatga qo'yamiz.
# Bitta worker ketma-ket yuboradi va Telegram flood limitini
# (429 TelegramRetryAfter) hurmat qiladi — bot event-loopi bloklanmaydi.
# Navbat to'lsa — yangi xabar TASHLAB yuboriladi (bot to'xtamaydi, RAM o'smaydi).
# ============================================================

_CHANNEL_QUEUE_MAXSIZE = 5000
_CHANNEL_PACING_SEC = 0.05  # ketma-ket yuborishlar orasida yumshoq pauza
_JOB_MAX_ATTEMPTS = 10      # flood/tarmoq xatosida job necha marta qayta navbatga qo'yiladi
_channel_queue: Optional[asyncio.Queue] = None

# Kanal hovuzi: har bir kanalga bitta worker, hammasi BITTA umumiy navbatdan oladi.
# Oddiy vaqtda hamma xabar ASOSIY kanalga boradi. Asosiy kanal flood'ga tushsa
# (yoki ishlamay qolsa) — qo'shimcha kanallar navbatni olib ketadi.
_channel_workers: dict[int, asyncio.Task] = {}
# chat_id -> {"title", "main", "sent", "flood_until", "error"}
channel_state: dict[int, dict] = {}


def _enqueue_channel_job(job: dict) -> None:
    """Ichki: job (dict) ni navbatga qo'yadi. Bloklamaydi; navbat to'lsa — tashlaydi."""
    if _channel_queue is None:
        return
    try:
        _channel_queue.put_nowait(job)
    except asyncio.QueueFull:
        logger.warning(
            "Channel queue to'la (%d) — job tashlab yuborildi (kind=%s)",
            _CHANNEL_QUEUE_MAXSIZE,
            job.get("kind"),
        )


def enqueue_channel(
    message: Message,
    direction: str,
    content_type: str,
    from_user_name: Optional[str],
) -> None:
    """Xabar NUSXASINI (media/matn) kanal navbatiga qo'yadi."""
    _enqueue_channel_job(
        {
            "kind": "copy",
            "message": message,
            "direction": direction,
            "content_type": content_type,
            "from_user_name": from_user_name,
        }
    )


def enqueue_channel_text(text: str) -> None:
    """Oddiy MATNLI bildirishnomani (tahrir/o'chirish) kanal navbatiga qo'yadi."""
    _enqueue_channel_job({"kind": "text", "text": text})


def enqueue_channel_media(
    content_type: str,
    file_id: Optional[str],
    header: str,
    body: str = "",
) -> None:
    """
    MEDIA (yoki matn) bildirishnomani kanal navbatiga qo'yadi.
    file_id bo'lsa — media qayta yuboriladi, header/body caption bo'ladi.
    file_id bo'lmasa — matn sifatida.
    """
    _enqueue_channel_job(
        {
            "kind": "media",
            "content_type": content_type,
            "file_id": file_id,
            "header": header,
            "body": body,
        }
    )


async def _run_channel_job(bot: Bot, channel_id: int, job: dict) -> None:
    """Bitta channel job ni bajaradi (nusxa / matn / media)."""
    kind = job.get("kind")
    if kind == "text":
        text = job["text"]
        if len(text) > 4096:
            text = text[:4093] + "..."
        await bot.send_message(chat_id=channel_id, text=text)
    elif kind == "media":
        await _send_media_by_id(
            bot,
            channel_id,
            job["content_type"],
            job.get("file_id"),
            job["header"],
            job.get("body", ""),
        )
    else:
        await _send_to_channel(
            bot,
            job["message"],
            channel_id,
            job["direction"],
            job["content_type"],
            job["from_user_name"],
        )


def _requeue(job: dict, reason: str) -> None:
    """Job'ni qayta navbatga qo'yadi (boshqa kanal oladi). Ko'p urinishdan keyin — tashlaydi."""
    job["attempts"] = job.get("attempts", 0) + 1
    if job["attempts"] > _JOB_MAX_ATTEMPTS:
        logger.error("Channel job %d urinishdan keyin tashlandi (kind=%s, %s)",
                     _JOB_MAX_ATTEMPTS, job.get("kind"), reason)
        return
    _enqueue_channel_job(job)


def _is_channel_lost(e: Exception) -> bool:
    """Bot kanaldan chiqarilgan / yozish huquqi yo'q / kanal o'chirilgan."""
    if isinstance(e, TelegramForbiddenError):
        return True
    msg = str(e).lower()
    return isinstance(e, (TelegramBadRequest, TelegramNotFound)) and any(
        s in msg for s in ("chat not found", "not enough rights", "have no rights",
                           "chat_write_forbidden", "need administrator rights")
    )


def _main_available() -> bool:
    """Asosiy kanal ishlayaptimi va flood'da emasmi."""
    main_id = next((cid for cid, s in channel_state.items() if s["main"]), None)
    if main_id is None or main_id not in _channel_workers:
        return False
    return asyncio.get_running_loop().time() >= channel_state[main_id]["flood_until"]


async def _channel_worker(bot: Bot, channel_id: int) -> None:
    """
    Umumiy navbatdan job olib, O'Z kanaliga yuboradi.

    Asosiy kanal — hamma xabarni oladi. Qo'shimcha kanallar FAQAT asosiy kanal
    flood'da yoki ishlamay qolganda navbatdan oladi (zaxira sifatida).
    """
    assert _channel_queue is not None
    loop = asyncio.get_running_loop()
    st = channel_state[channel_id]
    while True:
        if st["main"]:
            job = await _channel_queue.get()
        else:
            # Zaxira kanal: asosiy ishlayotgan bo'lsa — kutadi, navbatga tegmaydi
            if _main_available():
                await asyncio.sleep(0.5)
                continue
            try:
                job = _channel_queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.2)
                continue
        try:
            try:
                await _run_channel_job(bot, channel_id, job)
                st["sent"] += 1
                st["error"] = None
            except TelegramRetryAfter as e:
                st["flood_until"] = loop.time() + e.retry_after
                if len(_channel_workers) > 1:
                    # Boshqa kanallar bor — job ularga, bu kanal esa dam oladi
                    logger.warning("Kanal %s flood: %ss — xabar boshqa kanalga", channel_id, e.retry_after)
                    _requeue(job, "flood")
                    await asyncio.sleep(e.retry_after)
                else:
                    # Yagona kanal — kutib, shu job'ni qayta yuboramiz (tartib buzilmasin)
                    logger.warning("Channel flood limit: %ss kutilmoqda", e.retry_after)
                    await asyncio.sleep(e.retry_after)
                    try:
                        await _run_channel_job(bot, channel_id, job)
                        st["sent"] += 1
                    except Exception:
                        _requeue(job, "flood")
            except TelegramNetworkError as e:
                logger.warning("Kanal %s tarmoq xatosi: %s — qayta navbatga", channel_id, e)
                _requeue(job, "network")
                await asyncio.sleep(2)
            except Exception as e:
                if _is_channel_lost(e):
                    # Kanal ishlamaydi — job boshqa kanalga, bu worker to'xtaydi
                    logger.error("Kanal %s ishlamayapti (%s) — hovuzdan chiqarildi", channel_id, e)
                    st["error"] = str(e)[:200]
                    _requeue(job, "channel lost")
                    _channel_workers.pop(channel_id, None)
                    if not st["main"]:
                        await db.set_channel_active(channel_id, False)
                    return
                logger.error(
                    "Channelga yuborishda xato (kind=%s)", job.get("kind"), exc_info=True
                )
            # Yumshoq pacing — kanalga ketma-ket zarba bermaslik uchun
            await asyncio.sleep(_CHANNEL_PACING_SEC)
        finally:
            _channel_queue.task_done()


async def send_owner_text(bot: Bot, connection_id: str, text: str) -> None:
    """
    Owner (connection egasi = /start bosgan, botni ulagan xodim) ning
    shaxsiy chatiga matn yuboradi. Best-effort: xato bo'lsa bot to'xtamaydi.
    Manzil cache'dan olinadi — DB kerak emas.
    """
    chat_id = await _resolve_user_chat_id(bot, connection_id)
    if not chat_id:
        logger.warning(
            "Owner chat topilmadi (conn=%s) — bildirishnoma yuborilmadi", connection_id
        )
        return
    if len(text) > 4096:
        text = text[:4093] + "..."
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except TelegramRetryAfter as e:
        logger.warning("Owner send flood: %ss — o'tkazib yuborildi", e.retry_after)
    except Exception:
        logger.warning(
            "Owner ga yuborishda xato (conn=%s)", connection_id, exc_info=True
        )


async def _send_media_by_id(
    bot: Bot,
    chat_id: int,
    content_type: str,
    file_id: Optional[str],
    header: str,
    body: str = "",
    lang: str = "uz",
) -> None:
    """
    header (+ body) va kontentni chat_id ga yuboradi.

    - Media (file_id) bo'lsa: mos send_* bilan, header+body caption sifatida.
      sticker/video_note caption qo'llamaydi -> header alohida matn bo'lib ketadi.
    - file_id yo'q yoki matn tur -> header+body matn.
    - file_id ishlamasa -> yuklab qayta yuborish, u ham bo'lmasa -> matn fallback.

    TelegramRetryAfter — YUQORIGA uzatiladi (kanal worker qayta urinishi uchun).
    """
    full_text = f"{header}\n\n{body}".strip() if body else header

    # MUHIM: header ichida 👤 HTML havola bor -> parse_mode="HTML" bilan yuboramiz.
    # (Chaqiruvchi header/body dagi matnni html.escape qilib berishi shart.)

    # Media emas yoki file_id yo'q — matn ko'rinishida
    if not file_id or content_type in (
        "text", "contact", "location", "venue", "poll", "unknown",
    ):
        await bot.send_message(chat_id=chat_id, text=full_text[:4096], parse_mode="HTML")
        return

    caption = full_text if len(full_text) <= 1024 else full_text[:1021] + "..."

    # sticker / video_note — caption yo'q: avval matn, keyin media
    if content_type in ("sticker", "video_note"):
        try:
            await bot.send_message(chat_id=chat_id, text=full_text[:4096], parse_mode="HTML")
            if content_type == "sticker":
                await bot.send_sticker(chat_id=chat_id, sticker=file_id)
            else:
                await bot.send_video_note(chat_id=chat_id, video_note=file_id)
            return
        except TelegramRetryAfter:
            raise
        except Exception:
            ok = await _download_and_send_media(
                bot, chat_id, content_type, file_id, "file", "", False, False
            )
            if not ok:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"{full_text}\n[{content_type} — {t(lang, 'n_media_failed')}]"[:4096],
                    parse_mode="HTML",
                )
            return

    # captionli media turlari
    try:
        if content_type == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, parse_mode="HTML")
        elif content_type == "video":
            await bot.send_video(chat_id=chat_id, video=file_id, caption=caption, parse_mode="HTML")
        elif content_type == "audio":
            await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption, parse_mode="HTML")
        elif content_type == "voice":
            await bot.send_voice(chat_id=chat_id, voice=file_id, caption=caption, parse_mode="HTML")
        elif content_type == "document":
            await bot.send_document(chat_id=chat_id, document=file_id, caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(
                chat_id=chat_id, text=f"{full_text}\n[{content_type}]"[:4096], parse_mode="HTML"
            )
        return
    except TelegramRetryAfter:
        raise
    except Exception:
        ok = await _download_and_send_media(
            bot, chat_id, content_type, file_id, "file", caption, False, False, parse_mode="HTML"
        )
        if not ok:
            await bot.send_message(
                chat_id=chat_id,
                text=f"{full_text}\n[{content_type} — {t(lang, 'n_media_failed')}]"[:4096],
                parse_mode="HTML",
            )


async def send_owner_media(
    bot: Bot,
    connection_id: str,
    content_type: str,
    file_id: Optional[str],
    header: str,
    body: str = "",
    lang: Optional[str] = None,
) -> None:
    """Owner (connection egasi) chatiga media/matn bildirishnoma. Best-effort.

    lang berilmasa — owner'ning keshdagi tili aniqlanadi (fallback: inglizcha).
    """
    if lang is None:
        lang = owner_lang(connection_id)
    chat_id = await _resolve_user_chat_id(bot, connection_id)
    if not chat_id:
        logger.warning(
            "Owner chat topilmadi (conn=%s) — media bildirishnoma yuborilmadi",
            connection_id,
        )
        return
    try:
        await _send_media_by_id(bot, chat_id, content_type, file_id, header, body, lang=lang)
    except TelegramRetryAfter as e:
        logger.warning("Owner media send flood: %ss — o'tkazib yuborildi", e.retry_after)
    except Exception:
        logger.warning(
            "Owner ga media yuborishda xato (conn=%s)", connection_id, exc_info=True
        )


def add_channel_worker(bot: Bot, channel_id: int, title: Optional[str] = None, main: bool = False) -> bool:
    """Kanalni hovuzga qo'shadi (worker ishga tushadi). Allaqachon bo'lsa — False."""
    if _channel_queue is None or channel_id in _channel_workers:
        return False
    st = channel_state.setdefault(
        channel_id, {"title": title, "main": main, "sent": 0, "flood_until": 0.0, "error": None}
    )
    st["title"] = title or st["title"]
    st["error"] = None
    _channel_workers[channel_id] = asyncio.create_task(_channel_worker(bot, channel_id))
    logger.info("Kanal hovuzga qo'shildi: %s (%s) — jami %d", channel_id, title, len(_channel_workers))
    return True


async def remove_channel_worker(channel_id: int) -> bool:
    """Kanalni hovuzdan chiqaradi (worker to'xtaydi). Asosiy kanal chiqarilmaydi."""
    task = _channel_workers.get(channel_id)
    if task is None or channel_state.get(channel_id, {}).get("main"):
        return False
    _channel_workers.pop(channel_id, None)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Kanal hovuzdan chiqarildi: %s — qoldi %d", channel_id, len(_channel_workers))
    return True


def is_channel_working(channel_id: int) -> bool:
    return channel_id in _channel_workers


def channel_queue_size() -> int:
    return _channel_queue.qsize() if _channel_queue else 0


async def _load_extra_channels(bot: Bot) -> None:
    """Bazadagi faol qo'shimcha kanallarni hovuzga qo'shadi (startup)."""
    for ch in await db.get_channels():
        if ch["is_active"]:
            add_channel_worker(bot, ch["chat_id"], ch["title"])


def start_channel_worker(bot: Bot, channel_id: int) -> None:
    """on_startup da chaqiriladi — navbat, asosiy kanal va qo'shimcha kanallar."""
    global _channel_queue
    if _channel_queue is not None:
        return
    _channel_queue = asyncio.Queue(maxsize=_CHANNEL_QUEUE_MAXSIZE)
    add_channel_worker(bot, channel_id, main=True)
    asyncio.create_task(_load_extra_channels(bot))
    logger.info("Channel forward worker ishga tushdi (maxsize=%d)", _CHANNEL_QUEUE_MAXSIZE)


async def stop_channel_worker() -> None:
    """on_shutdown da chaqiriladi — hamma workerlarni to'xtatadi."""
    tasks = list(_channel_workers.values())
    _channel_workers.clear()
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _resolve_owner_id(
    bot: Bot, connection_id: str
) -> Optional[int]:
    """
    Connection egasining user_id sini aniqlaydi.

    Avval in-memory cache'dan qidiradi.
    Yo'q bo'lsa, get_business_connection API orqali oladi va cache'ga saqlaydi.
    """
    # Cache'dan
    owner_id = connection_owners.get(connection_id)
    if owner_id is not None:
        return owner_id

    # API'dan
    try:
        conn_info = await bot.get_business_connection(connection_id)
        owner_id = conn_info.user.id
        connection_owners[connection_id] = owner_id
        # Owner (egasi) ma'lumotini keshlaymiz — "Kimga" ni ko'rsatish uchun
        connection_owner_users[connection_id] = {
            "id": conn_info.user.id,
            "first_name": conn_info.user.first_name,
            "last_name": getattr(conn_info.user, "last_name", None),
            "username": conn_info.user.username,
            "language_code": getattr(conn_info.user, "language_code", None),
        }
        # user_chat_id ham saqlaymiz (forward uchun)
        user_chat_id = getattr(conn_info, "user_chat_id", None)
        if user_chat_id:
            connection_user_chats[connection_id] = user_chat_id
        logger.info(
            "Resolved owner for connection %s: user_id=%d, user_chat_id=%s",
            connection_id,
            owner_id,
            user_chat_id,
        )
        return owner_id
    except Exception:
        logger.warning(
            "Could not resolve owner for connection %s",
            connection_id,
            exc_info=True,
        )
        return None


async def _resolve_user_chat_id(
    bot: Bot, connection_id: str
) -> Optional[int]:
    """
    Connection egasining user_chat_id sini aniqlaydi (botning lichkasi).
    """
    chat_id = connection_user_chats.get(connection_id)
    if chat_id is not None:
        return chat_id

    # API'dan olish
    try:
        conn_info = await bot.get_business_connection(connection_id)
        user_chat_id = getattr(conn_info, "user_chat_id", None)
        if user_chat_id:
            connection_user_chats[connection_id] = user_chat_id
            connection_owners[connection_id] = conn_info.user.id
        return user_chat_id
    except Exception:
        logger.warning(
            "Could not resolve user_chat_id for connection %s",
            connection_id,
            exc_info=True,
        )
        return None


def _build_header(
    message: Message,
    direction: str,
    content_type: str,
    from_user_name: Optional[str],
) -> str:
    """
    Xabar ustidagi sarlavha — kim yubordi, qaysi chatdan.

    Masalan:
    📩 Mijoz: Ali @ali123
    👤 Chat: Ali
    """
    # Kim yubordi
    arrow = "📤" if direction == "outgoing" else "📩"
    role = "Xodim" if direction == "outgoing" else "Mijoz"
    header = f"{arrow} {role}: {from_user_name or '?'}"

    # Chat nomi
    if message.chat:
        chat_name = getattr(message.chat, "title", None) or getattr(message.chat, "first_name", None) or ""
        if chat_name:
            header += f"\n👤 Chat: {chat_name}"

    return header


async def _download_file(bot: Bot, file_id: str) -> Optional[bytes]:
    """
    Telegram serveridan faylni yuklab oladi.

    has_protected_content=true bo'lgan xabarlarning file_id sini
    to'g'ridan-to'g'ri send_photo/send_voice da ishlatib bo'lmaydi.
    Shu sababli avval yuklab olamiz, keyin yangi fayl sifatida yuboramiz.
    """
    try:
        # Semafor: bir vaqtda faqat N ta parallel yuklash (RAM/trafikni cheklaydi)
        async with _get_download_semaphore():
            file_info = await bot.get_file(file_id)
            if not file_info.file_path:
                return None
            result: io.BytesIO = await bot.download_file(file_info.file_path)
            return result.read()
    except Exception as e:
        logger.warning("Failed to download file %s: %s", file_id[:20], e)
        return None



async def _download_and_send_media(
    bot: Bot,
    chat_id: int,
    media_type: str,
    file_id: str,
    filename: str,
    caption: str,
    is_protected: bool,
    is_owner: bool,
    parse_mode: Optional[str] = None,
) -> bool:
    wait_msg = None
    if is_owner and is_protected:
        try:
            wait_msg = await bot.send_message(chat_id=chat_id, text="⏳")
        except Exception:
            pass

    data = await _download_file(bot, file_id)
    sent = False
    
    if data:
        final_caption = caption
        if is_owner and is_protected:
            try:
                bot_me = await bot.me()
                bot_username = bot_me.username
                if bot_username:
                    if final_caption:
                        final_caption += f"\\n\\n👉 @{bot_username}"
                    else:
                        final_caption = f"👉 @{bot_username}"
            except Exception:
                pass
                
        input_file = BufferedInputFile(data, filename=filename)
        try:
            if media_type == "photo":
                await bot.send_photo(chat_id=chat_id, photo=input_file, caption=final_caption, parse_mode=parse_mode)
            elif media_type == "video":
                await bot.send_video(chat_id=chat_id, video=input_file, caption=final_caption, parse_mode=parse_mode)
            elif media_type == "voice":
                await bot.send_voice(chat_id=chat_id, voice=input_file, caption=final_caption, parse_mode=parse_mode)
            elif media_type == "video_note":
                await bot.send_video_note(chat_id=chat_id, video_note=input_file)
                if is_owner and is_protected:
                    try:
                        bot_me = await bot.me()
                        bot_username = bot_me.username
                        if bot_username:
                            await bot.send_message(chat_id=chat_id, text=f"👉 @{bot_username}")
                    except Exception:
                        pass
            elif media_type == "audio":
                await bot.send_audio(chat_id=chat_id, audio=input_file, caption=final_caption, parse_mode=parse_mode)
            elif media_type == "document":
                await bot.send_document(chat_id=chat_id, document=input_file, caption=final_caption, parse_mode=parse_mode)
            elif media_type == "sticker":
                await bot.send_sticker(chat_id=chat_id, sticker=input_file)
            sent = True
        except Exception as e:
            logger.warning("Failed to send downloaded media %s: %s", media_type, e)
            
    if wait_msg:
        try:
            await wait_msg.delete()
        except Exception:
            pass
            
    return sent

async def _send_reply_media(
    bot: Bot,
    reply: Message,
    target_chat_id: int,
    is_owner: bool = False,
    answer_text: Optional[str] = None,
    answer_entities: Optional[list[MessageEntity]] = None,
) -> None:
    reply_type = detect_content_type(reply)
    is_protected = getattr(reply, "has_protected_content", False)

    # Javob berilgan (asl) xabar egasi — bosiladigan havola + @username + [ID]
    r_user = reply.from_user
    if r_user:
        rname = " ".join(p for p in [r_user.first_name or "", r_user.last_name or ""] if p) or None
        r_sender = full_user_html(rname, r_user.username, r_user.id)
    else:
        r_sender = "Noma'lum"

    # Chiroyli, to'liq sarlavha — "quyidagi xabarga javob berilgan"
    reply_header = (
        f"↩️ Javob berilgan xabar\n"
        f"👤 Kimdan: {r_sender}\n"
        f"🆔 Xabar ID: {reply.message_id}\n"
        f"📎 Turi: {reply_type}"
    )
    # Asl xabar forward bo'lsa — kimdan/qayerdan forward qilingani
    fwd = _forward_lines(reply)
    if fwd:
        reply_header += "\n" + "\n".join(fwd)

    # Asl xabar matni + shu xabarga yozilgan javob — asl formatlash (havola, qalin...) bilan
    if reply_type == "text" and reply.text:
        r_text, r_ents = reply.text, reply.entities
    else:
        r_text, r_ents = getattr(reply, "caption", None) or "", reply.caption_entities
        if not r_text:
            try:
                sp = special_content(reply, reply_type)
            except Exception:
                sp = None
            if sp:
                r_text, r_ents = sp[0], sp[1]
    parts = []
    if r_text:
        parts.append((r_text, r_ents))
    if answer_text:
        parts.append(("\n\n💬 Javob berildi:\n" if r_text else "💬 Javob berildi:\n", None))
        parts.append((answer_text, answer_entities))
    body_text, body_ents = _concat_text(*parts)

    # --- TEXT reply --- (uzun bo'lsa bo'lib yuboriladi)
    if reply_type == "text" and reply.text:
        await _send_long(bot, target_chat_id, f"{reply_header}\n✍️ Matn:", body_text, body_ents)
        return

    caption = reply_header
    # Kengaytirilgan media ma'lumotlari (file_id, o'lcham, davomiylik, ...)
    media_info = _extract_media_info(reply, reply_type)
    if media_info:
        caption += f"\n{html.escape(media_info)}"
    overflow = False
    if body_text:
        if _visible_len(caption) + 10 + _u16(body_text) <= _CAPTION_LIMIT:
            caption += f"\n✍️ Matn: {html_decoration.unparse(body_text, body_ents)}"
        else:
            overflow = True
    if _visible_len(caption) > _CAPTION_LIMIT:
        # Sarlavha sig'madi — matn qilib yuboramiz, media caption'siz ketadi
        await _send_html(bot, target_chat_id, caption)
        caption = ""

    await _send_reply_file(
        bot, reply, reply_type, target_chat_id, caption, is_protected, is_owner,
        fallback_text=caption,
    )

    if overflow:
        await _send_long(bot, target_chat_id, "✍️ Matn (to'liq):", body_text, body_ents)


async def _send_reply_file(
    bot: Bot,
    reply: Message,
    reply_type: str,
    target_chat_id: int,
    caption: str,
    is_protected: bool,
    is_owner: bool,
    fallback_text: str,
) -> None:
    """Javob berilgan xabarning faylini yuboradi. Fayl bo'lmasa — fallback_text."""
    file_id = None
    filename = "reply_file"
    if reply_type == "photo" and reply.photo:
        file_id = reply.photo[-1].file_id
        filename = "reply_photo.jpg"
    elif reply_type == "video" and reply.video:
        file_id = reply.video.file_id
        filename = "reply_video.mp4"
    elif reply_type == "voice" and reply.voice:
        file_id = reply.voice.file_id
        filename = "reply_voice.ogg"
    elif reply_type == "video_note" and reply.video_note:
        file_id = reply.video_note.file_id
        filename = "reply_videonote.mp4"
    elif reply_type == "audio" and reply.audio:
        file_id = reply.audio.file_id
        filename = "reply_audio.mp3"
    elif reply_type == "document" and reply.document:
        file_id = reply.document.file_id
        filename = reply.document.file_name or "reply_file"
    elif reply_type == "sticker" and reply.sticker:
        file_id = reply.sticker.file_id
        filename = "sticker.webp"

    if file_id:
        if is_protected and is_owner:
            if reply_type in ("video_note", "sticker"):
                await bot.send_message(chat_id=target_chat_id, text=caption, parse_mode="HTML")
                caption = ""
            await _download_and_send_media(bot, target_chat_id, reply_type, file_id, filename, caption, is_protected, is_owner, parse_mode="HTML")
            return

        # Try to send normally
        try:
            if reply_type == "photo":
                await bot.send_photo(chat_id=target_chat_id, photo=file_id, caption=caption, parse_mode="HTML")
            elif reply_type == "video":
                await bot.send_video(chat_id=target_chat_id, video=file_id, caption=caption, parse_mode="HTML")
            elif reply_type == "voice":
                await bot.send_message(chat_id=target_chat_id, text=caption, parse_mode="HTML")
                await bot.send_voice(chat_id=target_chat_id, voice=file_id)
            elif reply_type == "video_note":
                await bot.send_message(chat_id=target_chat_id, text=caption, parse_mode="HTML")
                await bot.send_video_note(chat_id=target_chat_id, video_note=file_id)
            elif reply_type == "audio":
                await bot.send_audio(chat_id=target_chat_id, audio=file_id, caption=caption, parse_mode="HTML")
            elif reply_type == "document":
                await bot.send_document(chat_id=target_chat_id, document=file_id, caption=caption, parse_mode="HTML")
            elif reply_type == "sticker":
                await bot.send_message(chat_id=target_chat_id, text=caption, parse_mode="HTML")
                await bot.send_sticker(chat_id=target_chat_id, sticker=file_id)
            return
        except Exception:
            pass

        # Fallback to download
        if reply_type in ("video_note", "sticker"):
            await bot.send_message(chat_id=target_chat_id, text=caption, parse_mode="HTML")
            caption = ""
        await _download_and_send_media(bot, target_chat_id, reply_type, file_id, filename, caption, is_protected, is_owner, parse_mode="HTML")
    elif fallback_text:
        await _send_html(bot, target_chat_id, fallback_text)


async def _send_copy_to_owner(
    bot: Bot,
    message: Message,
    user_chat_id: int,
) -> None:
    """
    Lichkaga faqat himoyalangan medianing o'zini yuboradi.
    Sarlavha yo'q, reply xabari yo'q.
    Faqat fayl + @bot_username.
    """
    content_type = detect_content_type(message)
    is_protected = getattr(message, "has_protected_content", False)

    # Bot username
    try:
        bot_me = await bot.me()
        bot_tag = f"👉 @{bot_me.username}" if bot_me.username else ""
    except Exception:
        bot_tag = ""

    file_id = None
    filename = "file"

    if content_type == "photo" and message.photo:
        file_id = message.photo[-1].file_id
        filename = "photo.jpg"
    elif content_type == "video" and message.video:
        file_id = message.video.file_id
        filename = "video.mp4"
    elif content_type == "voice" and message.voice:
        file_id = message.voice.file_id
        filename = "voice.ogg"
    elif content_type == "video_note" and message.video_note:
        file_id = message.video_note.file_id
        filename = "videonote.mp4"
    elif content_type == "audio" and message.audio:
        file_id = message.audio.file_id
        filename = "audio.mp3"
    elif content_type == "document" and message.document:
        file_id = message.document.file_id
        filename = message.document.file_name or "file"
    elif content_type == "sticker" and message.sticker:
        file_id = message.sticker.file_id
        filename = "sticker.webp"

    if not file_id:
        return

    caption = bot_tag
    if len(caption) > 1024:
        caption = caption[:1021] + "..."

    async def _send(source) -> bool:
        """source — file_id (str) yoki BufferedInputFile. Media turiga qarab yuboradi."""
        if content_type == "photo":
            await bot.send_photo(chat_id=user_chat_id, photo=source, caption=caption)
        elif content_type == "video":
            await bot.send_video(chat_id=user_chat_id, video=source, caption=caption)
        elif content_type == "voice":
            await bot.send_voice(chat_id=user_chat_id, voice=source, caption=caption)
        elif content_type == "video_note":
            await bot.send_video_note(chat_id=user_chat_id, video_note=source)
            if bot_tag:
                await bot.send_message(chat_id=user_chat_id, text=bot_tag)
        elif content_type == "audio":
            await bot.send_audio(chat_id=user_chat_id, audio=source, caption=caption)
        elif content_type == "document":
            await bot.send_document(chat_id=user_chat_id, document=source, caption=caption)
        elif content_type == "sticker":
            await bot.send_sticker(chat_id=user_chat_id, sticker=source)
            if bot_tag:
                await bot.send_message(chat_id=user_chat_id, text=bot_tag)
        else:
            return False
        return True

    # 1-usul: file_id ni to'g'ridan yuborish (kanal singari). Yuklab olish yo'q —
    # shuning uchun hajm cheklovi (20 MB) yo'q, katta videolar ham o'tadi.
    try:
        if await _send(file_id):
            return
    except Exception as e:
        logger.info("Direct file_id send failed, downloadga o'tamiz: %s", e)

    # 2-usul (fallback): yuklab olib qayta yuborish. Faqat <20 MB fayllarda ishlaydi.
    wait_msg = None
    try:
        wait_msg = await bot.send_message(chat_id=user_chat_id, text="⏳")
    except Exception:
        pass

    data = await _download_file(bot, file_id)
    if data:
        try:
            await _send(BufferedInputFile(data, filename=filename))
        except Exception as e:
            logger.warning("Failed to send protected media to owner: %s", e)

    # Qum soatni o'chirish
    if wait_msg:
        try:
            await wait_msg.delete()
        except Exception:
            pass


def _extract_media_info(msg: Message, ctype: str) -> str:
    lines = []
    if getattr(msg, "has_protected_content", False):
        lines.append("🔒 Himoyalangan (Protected): HA")
    if ctype == "photo" and msg.photo:
        lines.append(f"📄 File ID: {msg.photo[-1].file_id}")
        lines.append(f"📦 Size: {getattr(msg.photo[-1], 'file_size', 0)} bayt")
    elif ctype == "video" and msg.video:
        lines.append(f"📄 File ID: {msg.video.file_id}")
        lines.append(f"⏳ Davomiylik: {getattr(msg.video, 'duration', 0)}s")
        lines.append(f"📦 Size: {getattr(msg.video, 'file_size', 0)} bayt")
    elif ctype == "voice" and msg.voice:
        lines.append(f"📄 File ID: {msg.voice.file_id}")
        lines.append(f"⏳ Davomiylik: {getattr(msg.voice, 'duration', 0)}s")
    elif ctype == "video_note" and msg.video_note:
        lines.append(f"📄 File ID: {msg.video_note.file_id}")
        lines.append(f"⏳ Davomiylik: {getattr(msg.video_note, 'duration', 0)}s")
    elif ctype == "audio" and msg.audio:
        lines.append(f"📄 File ID: {msg.audio.file_id}")
        lines.append(f"⏳ Davomiylik: {getattr(msg.audio, 'duration', 0)}s")
    elif ctype == "document" and msg.document:
        lines.append(f"📄 File ID: {msg.document.file_id}")
        if msg.document.file_name:
            lines.append(f"📁 Nomi: {msg.document.file_name}")
    elif ctype == "sticker" and msg.sticker:
        lines.append(f"📄 File ID: {msg.sticker.file_id}")
        if msg.sticker.emoji:
            lines.append(f"😀 Emoji: {msg.sticker.emoji}")
        if getattr(msg.sticker, "set_name", None):
            lines.append(f"📚 Set: {msg.sticker.set_name}")
    return "\n".join(lines)


# ============================================================
# FORWARD / TASHQI JAVOB MA'LUMOTLARI va UZUN MATNNI BO'LISH
# ============================================================

_TEXT_LIMIT = 4096     # oddiy xabar chegarasi (ko'rinadigan belgi, UTF-16)
_CAPTION_LIMIT = 1024  # media caption chegarasi


def _u16(s: str) -> int:
    """Telegram uzunlikni UTF-16 birlikda sanaydi (emoji = 2)."""
    return len(s.encode("utf-16-le")) // 2


def _visible_len(html_text: str) -> int:
    """HTML matnning Telegram'da ko'rinadigan uzunligi (teglar sanalmaydi)."""
    return _u16(html.unescape(re.sub(r"<[^>]+>", "", html_text)))


def _ents(entities) -> list:
    # custom_emoji — oddiy bot yubora olmaydi (xato beradi), emoji belgisi matnda qoladi
    return [e for e in (entities or []) if e.type != "custom_emoji"]


def _concat_text(*parts: tuple) -> tuple[str, list]:
    """(matn, entity'lar) bo'laklarini bitta matnga qo'shadi, entity offset'larini suradi."""
    text, entities = "", []
    for part_text, part_ents in parts:
        shift = _u16(text)
        for e in _ents(part_ents):
            entities.append(e.model_copy(update={"offset": e.offset + shift}))
        text += part_text
    return text, entities


def _split_text(text: str, entities, first_limit: int, limit: int) -> list[tuple[str, list]]:
    """
    Matnni Telegram chegarasiga sig'adigan bo'laklarga ajratadi (iloji bo'lsa
    qator oxiridan). Har bo'lakka o'z entity'lari (qalin, havola, ...) kesib beriladi.
    """
    parts = []
    start, off16, cap = 0, 0, first_limit
    while start < len(text):
        end, size = start, 0
        while end < len(text) and size + _u16(text[end]) <= cap:
            size += _u16(text[end])
            end += 1
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start + (end - start) // 2:
                end = nl + 1
        end = max(end, start + 1)
        chunk = text[start:end]
        clen = _u16(chunk)
        chunk_ents = []
        for e in _ents(entities):
            s, f = max(e.offset, off16), min(e.offset + e.length, off16 + clen)
            if s < f:
                chunk_ents.append(e.model_copy(update={"offset": s - off16, "length": f - s}))
        parts.append((chunk, chunk_ents))
        start, off16, cap = end, off16 + clen, limit
    return parts


async def _send_html(bot: Bot, chat_id: int, text: str) -> None:
    """HTML matn yuboradi. Teg buzilgan bo'lsa — teglarsiz oddiy matn qilib qayta yuboradi."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except TelegramBadRequest as e:
        logger.warning("HTML yuborilmadi (%s) — oddiy matn bilan qayta", e)
        plain = html.unescape(re.sub(r"<[^>]+>", "", text))
        await bot.send_message(chat_id=chat_id, text=plain[:_TEXT_LIMIT], parse_mode=None)


async def _send_long(
    bot: Bot, chat_id: int, header: str, text: str, entities=None
) -> None:
    """
    header (HTML) + matn (asl formatlash bilan). 4096 dan oshsa — bir nechta
    xabarga bo'lib yuboradi: "📄 Davomi (2/3)".
    """
    room = _TEXT_LIMIT - _visible_len(header) - 2
    if room < 200:  # sarlavha juda uzun — alohida yuboramiz
        await _send_html(bot, chat_id, header)
        header, room = "", _TEXT_LIMIT
    parts = _split_text(text, entities, room, _TEXT_LIMIT - 40)
    for i, (chunk, chunk_ents) in enumerate(parts):
        body = html_decoration.unparse(chunk, chunk_ents)
        if i == 0:
            msg = f"{header}\n\n{body}" if header else body
        else:
            msg = f"📄 Davomi ({i + 1}/{len(parts)})\n\n{body}"
        await _send_html(bot, chat_id, msg)


async def _send_photos(bot: Bot, chat_id: int, file_ids: list[str]) -> None:
    """Maqola (rich_message) ichidagi rasmlar — 10 tadan albom qilib. Xato bo'lsa bot yiqilmaydi."""
    for i in range(0, len(file_ids), 10):
        group = [InputMediaPhoto(media=fid) for fid in file_ids[i:i + 10]]
        try:
            if len(group) == 1:
                await bot.send_photo(chat_id=chat_id, photo=group[0].media)
            else:
                await bot.send_media_group(chat_id=chat_id, media=group)
        except TelegramRetryAfter:
            raise
        except Exception as e:
            logger.warning("Maqola rasmlari yuborilmadi: %s", e)


def _chat_html(chat) -> str:
    """Guruh/kanal: 'Nomi' (username bo'lsa havola) @username [ID: -100...]."""
    name = getattr(chat, "title", None) or " ".join(
        p for p in [getattr(chat, "first_name", None), getattr(chat, "last_name", None)] if p
    )
    username = getattr(chat, "username", None)
    out = user_link_html(name or None, username, None)
    if username:
        out += f" @{html.escape(username)}"
    return out + f" [ID: {chat.id}]"


def _post_link(chat, message_id: Optional[int]) -> Optional[str]:
    """Kanal/guruhdagi asl postga havola (ochiq yoki yopiq kanal)."""
    if not chat or not message_id:
        return None
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}/{message_id}"
    cid = str(chat.id)
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return None


def _origin_lines(origin) -> list[str]:
    """MessageOrigin (user / hidden_user / chat / channel) — asl manba haqida hamma ma'lumot."""
    lines = []
    otype = getattr(origin, "type", None)
    if otype == "user":
        u = origin.sender_user
        name = " ".join(p for p in [u.first_name or "", u.last_name or ""] if p) or None
        bot_mark = " 🤖 (bot)" if u.is_bot else ""
        lines.append(f"👤 Asl yuboruvchi: {full_user_html(name, u.username, u.id)}{bot_mark}")
    elif otype == "hidden_user":
        lines.append(
            f"👤 Asl yuboruvchi: {html.escape(origin.sender_user_name or '?')} (profili yashirin)"
        )
    elif otype == "chat":
        lines.append(f"👥 Guruhdan (anonim admin): {_chat_html(origin.sender_chat)}")
    elif otype == "channel":
        lines.append(f"📢 Kanaldan: {_chat_html(origin.chat)}")
        link = _post_link(origin.chat, origin.message_id)
        if link:
            lines.append(f'🔗 <a href="{html.escape(link)}">Asl postni ochish</a> (ID: {origin.message_id})')
        else:
            lines.append(f"🆔 Asl post ID: {origin.message_id}")
    sig = getattr(origin, "author_signature", None)
    if sig:
        lines.append(f"✍️ Imzo: {html.escape(sig)}")
    if getattr(origin, "date", None):
        lines.append(f"🕐 Asl vaqti: {origin.date.strftime('%Y-%m-%d %H:%M:%S')} (UTC+0)")
    return lines


def _forward_lines(msg: Message) -> list[str]:
    """
    Xabar qayerdan kelgani: forward manbasi, bot orqali, boshqa chatdagi xabarga
    javob, iqtibos. Telegram bergan hamma ma'lumot chiqariladi.
    """
    lines = []
    if msg.forward_origin:
        lines.append("🔁 Forward qilingan xabar:")
        lines += [f"   {line}" for line in _origin_lines(msg.forward_origin)]
    if getattr(msg, "is_automatic_forward", None):
        lines.append("📢 Kanaldan guruhga avtomatik uzatilgan")
    if msg.via_bot:
        vb = msg.via_bot
        lines.append(f"🤖 Bot orqali yuborilgan: {full_user_html(vb.first_name, vb.username, vb.id)}")
    ext = getattr(msg, "external_reply", None)
    if ext:
        lines.append("↪️ Boshqa chatdagi xabarga javob:")
        if ext.chat:
            lines.append(f"   💬 Chat: {_chat_html(ext.chat)}")
            link = _post_link(ext.chat, ext.message_id)
            if link:
                lines.append(f'   🔗 <a href="{html.escape(link)}">Xabarni ochish</a>')
        lines += [f"   {line}" for line in _origin_lines(ext.origin)]
    quote = getattr(msg, "quote", None)
    if quote and quote.text:
        lines.append(f"❝ Iqtibos: {html.escape(quote.text)}")
    return lines


def _build_channel_header(
    message: Message,
    direction: str,
    content_type: str,
    from_user_name: Optional[str],
) -> str:
    """
    Kanal uchun batafsil sarlavha — kim yubordi, kimga, tur, vaqt.

    Masalan:
    📩 Yangi xabar
    👤 Kimdan: Ali Valiyev @ali123
    💬 Kimga: Sardor @sardor
    📎 Turi: photo
    🕐 Vaqt: 2026-06-29 15:30
    """
    arrow = "📤" if direction == "outgoing" else "📩"

    if message.business_connection_id:
        lines = [f"{arrow} Yangi xabar"]
    else:
        lines = ["🤖 Botga to'g'ridan-to'g'ri yozildi"]

    # Business chat = owner <-> mijoz. Chat obyekti doim MIJOZ ni bildiradi.
    #   outgoing (owner yozdi):  Kimdan = owner (from_user),  Kimga = mijoz (chat)
    #   incoming (mijoz yozdi):  Kimdan = mijoz (from_user), Kimga = owner
    conn_id = message.business_connection_id

    # Kimdan = yuboruvchi — bosiladigan havola (tg://user?id=) + @username + [ID]
    if message.from_user:
        u = message.from_user
        name = " ".join(p for p in [u.first_name or "", u.last_name or ""] if p) or None
        kimdan = full_user_html(name, u.username, u.id)
    else:
        kimdan = html.escape(from_user_name or "?")
    lines.append(f"👤 Kimdan: {kimdan}")

    # Kimga = oluvchi — bosiladigan havola
    if direction == "outgoing":
        kimga = chat_link_html(message.chat) if message.chat else None
    else:
        kimga = owner_link_html(conn_id)
    if kimga:
        lines.append(f"➡️ Kimga: {kimga}")

    # Agar xabar reply (javob) bo'lsa
    if message.reply_to_message:
        reply_user = message.reply_to_message.from_user
        if reply_user:
            rname = " ".join(
                p for p in [reply_user.first_name or "", reply_user.last_name or ""] if p
            ) or None
            lines.append(
                f"⤴️ Javob berilgan: {full_user_html(rname, reply_user.username, reply_user.id)}"
            )
        else:
            lines.append("⤴️ Javob berilgan: (oldingi xabarga)")

    # Forward / bot orqali / boshqa chatga javob / iqtibos
    lines += _forward_lines(message)

    # Xabar turi
    lines.append(f"📎 Turi: {content_type}")

    # Kengaytirilgan media ma'lumotlari (escape — file nomi/emoji xavfsiz bo'lsin)
    media_info = _extract_media_info(message, content_type)
    if media_info:
        lines.append(html.escape(media_info))

    # Vaqt
    if message.date:
        lines.append(f"🕐 Vaqt: {message.date.strftime('%Y-%m-%d %H:%M:%S')} (UTC+0)")

    return "\n".join(lines)


async def _send_to_channel(
    bot: Bot,
    message: Message,
    channel_id: int,
    direction: str,
    content_type: str,
    from_user_name: Optional[str],
) -> None:
    """
    Xabar nusxasini kanalga to'liq ma'lumot bilan yuboradi.

    Har bir tur uchun mos send_* metodi ishlatiladi.
    Protected content bo'lsa — yuklab olib qayta yuboriladi.
    """
    header = _build_channel_header(message, direction, content_type, from_user_name)

    # --- Reply (javob berilgan) xabar bloki: asl xabar + unga yozilgan javob ---
    if message.reply_to_message:
        answer_text = message.text or getattr(message, "caption", None)
        answer_entities = message.entities if message.text else message.caption_entities
        try:
            await _send_reply_media(
                bot,
                message.reply_to_message,
                channel_id,
                answer_text=answer_text,
                answer_entities=answer_entities,
            )
        except TelegramRetryAfter:
            raise
        except Exception as e:
            logger.warning("Could not send reply media to channel: %s", e)

    # --- TEXT --- (asl formatlash saqlanadi, uzun bo'lsa bo'lib yuboriladi)
    if content_type == "text" and message.text:
        await _send_long(bot, channel_id, header, message.text, message.entities)
        return

    # --- SO'ROVNOMA / STORY / SOVG'A / PIN / MAQOLA / ... --- to'liq tavsif bilan
    special = None
    try:
        special = special_content(message, content_type)
    except Exception:
        logger.warning("special_content xato (msg_id=%s)", message.message_id, exc_info=True)
    if special:
        sp_text, sp_ents, sp_photos = special
        await _send_long(bot, channel_id, header, sp_text or f"[{content_type}]", sp_ents)
        await _send_photos(bot, channel_id, sp_photos)
        return

    # Caption bilan sarlavhani birlashtirish (media turlar uchun).
    # Sig'masa: media faqat sarlavha bilan, caption matni keyin alohida xabar(lar)da.
    original_caption = getattr(message, "caption", None) or ""
    caption_html = html_decoration.unparse(original_caption, _ents(message.caption_entities))
    has_caption = content_type in ("photo", "video", "audio", "document")
    caption, overflow = header, bool(original_caption)
    if (
        has_caption
        and original_caption
        and _visible_len(header) + 2 + _u16(original_caption) <= _CAPTION_LIMIT
    ):
        caption, overflow = f"{header}\n\n{caption_html}", False
    if has_caption and _visible_len(caption) > _CAPTION_LIMIT:
        # Sarlavhaning o'zi sig'madi — uni matn qilib oldinroq yuboramiz
        await _send_html(bot, channel_id, header)
        caption = ""

    await _send_channel_media(bot, message, channel_id, content_type, header, caption)

    if overflow:
        await _send_long(
            bot, channel_id, "✍️ Xabar matni (to'liq):",
            original_caption, message.caption_entities,
        )


async def _send_channel_media(
    bot: Bot,
    message: Message,
    channel_id: int,
    content_type: str,
    header: str,
    caption: str,
) -> None:
    """Xabarning mediasini kanalga yuboradi (turiga qarab). caption — tayyor HTML."""
    # --- PHOTO ---
    if content_type == "photo" and message.photo:
        largest = message.photo[-1]
        try:
            await bot.send_photo(chat_id=channel_id, photo=largest.file_id, caption=caption)
            return
        except Exception:
            pass
        data = await _download_file(bot, largest.file_id)
        if data:
            await bot.send_photo(
                chat_id=channel_id,
                photo=BufferedInputFile(data, filename="photo.jpg"),
                caption=caption,
            )
            return

    # --- VIDEO ---
    if content_type == "video" and message.video:
        try:
            await bot.send_video(chat_id=channel_id, video=message.video.file_id, caption=caption)
            return
        except Exception:
            pass
        data = await _download_file(bot, message.video.file_id)
        if data:
            await bot.send_video(
                chat_id=channel_id,
                video=BufferedInputFile(data, filename="video.mp4"),
                caption=caption,
            )
            return

    # --- VOICE ---
    if content_type == "voice" and message.voice:
        await bot.send_message(chat_id=channel_id, text=header)
        try:
            await bot.send_voice(chat_id=channel_id, voice=message.voice.file_id)
            return
        except Exception:
            pass
        data = await _download_file(bot, message.voice.file_id)
        if data:
            await bot.send_voice(
                chat_id=channel_id,
                voice=BufferedInputFile(data, filename="voice.ogg"),
            )
            return

    # --- VIDEO_NOTE ---
    if content_type == "video_note" and message.video_note:
        await bot.send_message(chat_id=channel_id, text=header)
        try:
            await bot.send_video_note(chat_id=channel_id, video_note=message.video_note.file_id)
            return
        except Exception:
            pass
        data = await _download_file(bot, message.video_note.file_id)
        if data:
            await bot.send_video_note(
                chat_id=channel_id,
                video_note=BufferedInputFile(data, filename="videonote.mp4"),
            )
            return

    # --- AUDIO ---
    if content_type == "audio" and message.audio:
        try:
            await bot.send_audio(chat_id=channel_id, audio=message.audio.file_id, caption=caption)
            return
        except Exception:
            pass
        data = await _download_file(bot, message.audio.file_id)
        if data:
            await bot.send_audio(
                chat_id=channel_id,
                audio=BufferedInputFile(data, filename="audio.mp3"),
                caption=caption,
            )
            return

    # --- DOCUMENT ---
    if content_type == "document" and message.document:
        try:
            await bot.send_document(chat_id=channel_id, document=message.document.file_id, caption=caption)
            return
        except Exception:
            pass
        data = await _download_file(bot, message.document.file_id)
        if data:
            fname = message.document.file_name or "file"
            await bot.send_document(
                chat_id=channel_id,
                document=BufferedInputFile(data, filename=fname),
                caption=caption,
            )
            return

    # --- STICKER ---
    if content_type == "sticker" and message.sticker:
        await bot.send_message(chat_id=channel_id, text=header)
        try:
            await bot.send_sticker(chat_id=channel_id, sticker=message.sticker.file_id)
            return
        except Exception:
            pass

    # --- CONTACT ---
    if content_type == "contact" and message.contact:
        await bot.send_message(chat_id=channel_id, text=header)
        await bot.send_contact(
            chat_id=channel_id,
            phone_number=message.contact.phone_number,
            first_name=message.contact.first_name,
            last_name=message.contact.last_name,
        )
        return

    # --- LOCATION ---
    if content_type == "location" and message.location:
        await bot.send_message(chat_id=channel_id, text=header)
        await bot.send_location(
            chat_id=channel_id,
            latitude=message.location.latitude,
            longitude=message.location.longitude,
        )
        return

    # --- VENUE ---
    if content_type == "venue" and message.venue:
        await bot.send_message(chat_id=channel_id, text=header)
        await bot.send_venue(
            chat_id=channel_id,
            latitude=message.venue.location.latitude,
            longitude=message.venue.location.longitude,
            title=message.venue.title,
            address=message.venue.address,
        )
        return

    # --- BOSHQA ---
    fallback = f"{header}\n\n[{content_type}]"
    await bot.send_message(chat_id=channel_id, text=fallback)


@router.business_message()
async def on_business_message(message: Message, bot: Bot) -> None:
    """Yangi business xabarni qayta ishlaydi."""

    connection_id = message.business_connection_id
    if not connection_id:
        return

    # --- 1. Content type aniqlash ---
    content_type = detect_content_type(message)

    # --- 2. Direction aniqlash ---
    from_user_id = message.from_user.id if message.from_user else None
    owner_id = await _resolve_owner_id(bot, connection_id)
    direction = determine_direction(from_user_id, owner_id)

    # --- 3. Matn/caption ajratish ---
    text = extract_text_or_caption(message, content_type)

    # --- 4. Media maydonlar ---
    media = extract_media_fields(message, content_type)

    # --- 5. raw_json tayyorlash ---
    try:
        raw_json = json.loads(
            message.model_dump_json(exclude_none=True, by_alias=True)
        )
    except Exception:
        raw_json = {"error": "failed to serialize"}

    # --- 6. tg_date ---
    tg_date: Optional[datetime] = None
    if message.date:
        tg_date = message.date.replace(tzinfo=timezone.utc) if message.date.tzinfo is None else message.date

    # --- 7. Umumiy ma'lumotlar ---
    from_user_name = None
    if message.from_user:
        parts = [message.from_user.first_name or ""]
        if message.from_user.username:
            parts.append(f"@{message.from_user.username}")
        from_user_name = " ".join(parts).strip() or None

    chat_type = message.chat.type if message.chat else None
    chat_title = None
    chat_username = None
    if message.chat:
        chat_title = getattr(message.chat, "title", None)
        chat_username = getattr(message.chat, "username", None)

    # --- 8. Logga chiqarish ---
    text_preview = (text[:80] + "...") if text and len(text) > 80 else text
    
    reply_log_info = ""
    reply_extra = {}
    if message.reply_to_message:
        r_msg = message.reply_to_message
        r_type = detect_content_type(r_msg)
        r_full_text = r_msg.text or r_msg.caption or f"[{r_type}]"
        reply_log_info = f" | REPLY_TO: id={r_msg.message_id} type={r_type} full_text={r_full_text}"
        
        try:
            r_raw = json.loads(r_msg.model_dump_json(exclude_none=True, by_alias=True))
        except Exception:
            r_raw = {}
            
        reply_extra = {
            "reply_to_message_id": r_msg.message_id,
            "reply_to_type": r_type,
            "reply_to_full_text": r_full_text,
            "reply_to_raw_data": r_raw
        }

    logger.info(
        "[%s] %s | conn=%s chat=%d from=%s(%s) msg_id=%d type=%s | %s%s",
        direction.upper(),
        "business_message",
        connection_id[:8],
        message.chat.id if message.chat else 0,
        from_user_id,
        from_user_name or "?",
        message.message_id,
        content_type,
        text_preview or f"[{content_type}]",
        reply_log_info,
        extra={
            "update_type": "business_message",
            "connection_id": connection_id,
            "chat_id": message.chat.id if message.chat else None,
            "from_user_id": from_user_id,
            "from_user_name": from_user_name,
            "direction": direction,
            "content_type": content_type,
            "text_preview": text_preview,
            **reply_extra
        },
    )

    # --- 9. Lichkaga faqat CLIENT tomonidan yuborilgan is_protected xabarga reply bo'lsa ---
    # Bot standalone protected xabarni yuklay olmaydi (Telegram cheklov).
    # Faqat reply_to_message kontekstida protected mediani o'qish mumkin.
    # MUHIM: reply_to_message EGA TOMONIDAN (owner) yuborilgan bo'lmasligi kerak.
    # Ya'ni: faqat clientning protected xabari saqlangan bo'lsin.
    _reply_msg = message.reply_to_message
    _reply_is_protected = (
        _reply_msg is not None
        and getattr(_reply_msg, "has_protected_content", False)
        and _reply_msg.from_user is not None
        and _reply_msg.from_user.id != owner_id  # owner o'z xabariga reply qilsa — saqlanmaydi
    )

    if _reply_is_protected:
        user_chat_id = await _resolve_user_chat_id(bot, connection_id)
        if user_chat_id:
            try:
                # Clientning protected mediasini lichkaga yuboramiz
                await _send_copy_to_owner(bot, _reply_msg, user_chat_id)
                logger.info(
                    "Sent client's protected reply media (reply_msg_id=%d, from_user=%d) to owner chat=%d",
                    _reply_msg.message_id,
                    _reply_msg.from_user.id,
                    user_chat_id,
                )
            except Exception:
                logger.error(
                    "Failed to send client's protected reply media to owner chat=%d",
                    user_chat_id,
                    exc_info=True,
                )

    # --- 10. Bazaga yozish ---
    await db.insert_message(
        connection_id=connection_id,
        chat_id=message.chat.id if message.chat else 0,
        from_user_id=from_user_id,
        from_user_name=from_user_name,
        message_id=message.message_id,
        direction=direction,
        content_type=content_type,
        text=text,
        media_file_id=media["media_file_id"],
        media_file_name=media["media_file_name"],
        media_mime=media["media_mime"],
        media_duration=media["media_duration"],
        is_edited=False,
        raw_json=raw_json,
        tg_date=tg_date,
    )

    # --- 11. Kanalga nusxa yuborish (fon navbati orqali — bloklanmaydi) ---
    # To'g'ridan yuborish o'rniga navbatga qo'yamiz. Bitta worker ketma-ket
    # yuboradi va flood limitini hurmat qiladi. Bu qadam bir zumda bajariladi.
    if settings.channel_id:
        enqueue_channel(message, direction, content_type, from_user_name)

    # --- 12. Chat jadvalini yangilash ---
    if message.chat:
        await db.upsert_chat(
            connection_id=connection_id,
            chat_id=message.chat.id,
            chat_type=chat_type,
            title=chat_title,
            username=chat_username,
        )
