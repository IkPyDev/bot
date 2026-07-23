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
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile, Message

from app.config import settings
from app.db import db
from app.extractors import (
    detect_content_type,
    determine_direction,
    extract_media_fields,
    extract_text_or_caption,
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

_CHANNEL_QUEUE_MAXSIZE = 1000
_CHANNEL_PACING_SEC = 0.05  # ketma-ket yuborishlar orasida yumshoq pauza
_channel_queue: Optional[asyncio.Queue] = None
_channel_worker_task: Optional[asyncio.Task] = None


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


async def _channel_worker(bot: Bot, channel_id: int) -> None:
    """Navbatdan job olib, kanalga ketma-ket yuboradi (429 ni hurmat qiladi)."""
    assert _channel_queue is not None
    while True:
        job = await _channel_queue.get()
        try:
            try:
                await _run_channel_job(bot, channel_id, job)
            except TelegramRetryAfter as e:
                # Flood limit — Telegram aytgancha kutamiz va bir marta qayta urinamiz
                logger.warning("Channel flood limit: %ss kutilmoqda", e.retry_after)
                await asyncio.sleep(e.retry_after)
                try:
                    await _run_channel_job(bot, channel_id, job)
                except Exception:
                    logger.error(
                        "Channel job retry ham muvaffaqiyatsiz (kind=%s)",
                        job.get("kind"),
                        exc_info=True,
                    )
            except Exception:
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


def start_channel_worker(bot: Bot, channel_id: int) -> None:
    """on_startup da chaqiriladi — navbat va workerni ishga tushiradi."""
    global _channel_queue, _channel_worker_task
    if _channel_worker_task is not None:
        return
    _channel_queue = asyncio.Queue(maxsize=_CHANNEL_QUEUE_MAXSIZE)
    _channel_worker_task = asyncio.create_task(_channel_worker(bot, channel_id))
    logger.info("Channel forward worker ishga tushdi (maxsize=%d)", _CHANNEL_QUEUE_MAXSIZE)


async def stop_channel_worker() -> None:
    """on_shutdown da chaqiriladi — workerni to'xtatadi."""
    global _channel_worker_task
    if _channel_worker_task is not None:
        _channel_worker_task.cancel()
        try:
            await _channel_worker_task
        except asyncio.CancelledError:
            pass
        _channel_worker_task = None


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

    # Shu xabarga nima deb javob yozilgani (asosiy xabar matni/caption'i)
    answer_suffix = ""
    if answer_text:
        answer_suffix = f"\n\n💬 Javob berildi:\n{html.escape(answer_text)}"

    # --- TEXT reply ---
    if reply_type == "text" and reply.text:
        text = f"{reply_header}\n✍️ Matn:\n{html.escape(reply.text)}{answer_suffix}"
        if len(text) > 4096:
            text = text[:4093] + "..."
        await bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML")
        return

    reply_caption = getattr(reply, "caption", None) or ""

    caption = reply_header
    # Kengaytirilgan media ma'lumotlari (file_id, o'lcham, davomiylik, ...)
    media_info = _extract_media_info(reply, reply_type)
    if media_info:
        caption += f"\n{html.escape(media_info)}"
    if reply_caption:
        caption += f"\n✍️ Matn: {html.escape(reply_caption)}"
    caption += answer_suffix
    if len(caption) > 1024:
        caption = caption[:1021] + "..."

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
    else:
        await bot.send_message(chat_id=target_chat_id, text=reply_header + answer_suffix, parse_mode="HTML")


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

    lines = [f"{arrow} Yangi xabar"]

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
        try:
            await _send_reply_media(
                bot, message.reply_to_message, channel_id, answer_text=answer_text
            )
        except Exception as e:
            logger.warning("Could not send reply media to channel: %s", e)

    # --- TEXT ---
    if content_type == "text" and message.text:
        full_text = f"{header}\n\n{html.escape(message.text)}"
        if len(full_text) > 4096:
            full_text = full_text[:4093] + "..."
        await bot.send_message(chat_id=channel_id, text=full_text)
        return

    # Caption bilan sarlavhani birlashtirish (media turlar uchun)
    original_caption = html.escape(getattr(message, "caption", None) or "")
    caption = f"{header}\n\n{original_caption}".strip() if original_caption else header
    if len(caption) > 1024:
        caption = caption[:1021] + "..."

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
