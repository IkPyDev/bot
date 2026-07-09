"""
DEBUG / TEST rejimi — Spec 13-band.

Baza YO'Q. Faqat to'liq log.
Maqsad: qanday ma'lumotlar kelishini ko'rish.

Har bir update uchun:
- Qisqa xulosa (update turi, content_type, direction, connection_id, chat_id, ism, matn preview)
- To'liq JSON (model_dump_json, exclude_none=True, by_alias=True)

Bot hech kimga javob YOZMAYDI.

Ishga tushirish:
    python debug_bot.py
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ---- Logging sozlash (JSON format, konsol + fayl) ----

from app.logger import setup_logger

debug_logger = setup_logger(
    name="debug_bot",
    level=os.getenv("LOG_LEVEL", "DEBUG"),
    log_file=os.getenv("LOG_FILE", "logs/debug_bot.log"),
)

# aiogram logging
logging.getLogger("aiogram").setLevel(logging.WARNING)

# ---- aiogram import ----

from aiogram import Bot, Dispatcher, Router
from aiogram.types import (
    BusinessConnection,
    BusinessMessagesDeleted,
    Message,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    debug_logger.error("BOT_TOKEN environment variable is required!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router(name="debug")

# ---- Connection owners cache (direction aniqlash uchun) ----
# connection_id → owner user_id
connection_owners: dict[str, int] = {}


async def _resolve_owner(connection_id: str) -> Optional[int]:
    """Owner user_id ni cache yoki API orqali aniqlaydi."""
    owner_id = connection_owners.get(connection_id)
    if owner_id is not None:
        return owner_id

    try:
        conn_info = await bot.get_business_connection(connection_id)
        owner_id = conn_info.user.id
        connection_owners[connection_id] = owner_id
        debug_logger.info("Resolved owner for %s: user_id=%d", connection_id, owner_id)
        return owner_id
    except Exception:
        debug_logger.warning("Could not resolve owner for %s", connection_id, exc_info=True)
        return None


def _direction(from_user_id: Optional[int], owner_id: Optional[int]) -> str:
    """incoming yoki outgoing."""
    if from_user_id and owner_id and from_user_id == owner_id:
        return "outgoing"
    return "incoming"


def _full_json(obj) -> str:
    """Obyektni to'liq JSON formatda qaytaradi."""
    try:
        return obj.model_dump_json(indent=2, exclude_none=True, by_alias=True)
    except Exception as e:
        return f'{{"error": "{e}"}}'


# ============================================================
# 1. business_connection
# ============================================================

@router.business_connection()
async def on_business_connection(event: BusinessConnection) -> None:
    # Owner cache
    connection_owners[event.id] = event.user.id

    status = "ENABLED" if event.is_enabled else "DISABLED"
    can_reply = getattr(event, "can_reply", None)

    # Qisqa xulosa
    debug_logger.info(
        "📡 BUSINESS_CONNECTION | id=%s | user=%d (@%s, %s) | status=%s | can_reply=%s",
        event.id,
        event.user.id,
        event.user.username or "",
        event.user.first_name or "",
        status,
        can_reply,
    )

    # To'liq JSON
    debug_logger.info("📡 BUSINESS_CONNECTION FULL JSON:\n%s", _full_json(event))


# ============================================================
# 2. business_message
# ============================================================

@router.business_message()
async def on_business_message(message: Message) -> None:
    connection_id = message.business_connection_id or "?"

    # Content type
    content_type = _detect_type(message)

    # Direction
    from_user_id = message.from_user.id if message.from_user else None
    owner_id = await _resolve_owner(connection_id) if connection_id != "?" else None
    direction = _direction(from_user_id, owner_id)

    # Matn preview
    text = message.text or getattr(message, "caption", None) or ""
    preview = (text[:80] + "...") if len(text) > 80 else text

    # Kim yozgani
    from_name = ""
    if message.from_user:
        from_name = f"{message.from_user.first_name or ''} @{message.from_user.username or ''}"

    # Qisqa xulosa
    debug_logger.info(
        "💬 BUSINESS_MESSAGE [%s] | type=%s | conn=%s | chat=%d | from=%s(%s) | msg_id=%d | %s",
        direction.upper(),
        content_type,
        connection_id[:12],
        message.chat.id if message.chat else 0,
        from_user_id,
        from_name.strip(),
        message.message_id,
        preview or f"[{content_type}]",
    )

    # To'liq JSON
    debug_logger.info("💬 BUSINESS_MESSAGE FULL JSON:\n%s", _full_json(message))


# ============================================================
# 3. edited_business_message
# ============================================================

@router.edited_business_message()
async def on_edited_business_message(message: Message) -> None:
    connection_id = message.business_connection_id or "?"
    content_type = _detect_type(message)

    from_user_id = message.from_user.id if message.from_user else None
    owner_id = await _resolve_owner(connection_id) if connection_id != "?" else None
    direction = _direction(from_user_id, owner_id)

    text = message.text or getattr(message, "caption", None) or ""
    preview = (text[:80] + "...") if len(text) > 80 else text

    from_name = ""
    if message.from_user:
        from_name = f"{message.from_user.first_name or ''} @{message.from_user.username or ''}"

    debug_logger.info(
        "✏️ EDITED_BUSINESS_MESSAGE [%s] | type=%s | conn=%s | chat=%d | from=%s(%s) | msg_id=%d | %s",
        direction.upper(),
        content_type,
        connection_id[:12],
        message.chat.id if message.chat else 0,
        from_user_id,
        from_name.strip(),
        message.message_id,
        preview or f"[{content_type}]",
    )

    debug_logger.info("✏️ EDITED_BUSINESS_MESSAGE FULL JSON:\n%s", _full_json(message))


# ============================================================
# 4. deleted_business_messages
# ============================================================

@router.deleted_business_messages()
async def on_deleted_business_messages(event: BusinessMessagesDeleted) -> None:
    connection_id = event.business_connection_id or "?"
    chat_id = event.chat.id if event.chat else 0

    debug_logger.info(
        "🗑️ DELETED_BUSINESS_MESSAGES | conn=%s | chat=%d | %d messages: %s",
        connection_id[:12],
        chat_id,
        len(event.message_ids),
        event.message_ids,
    )

    debug_logger.info("🗑️ DELETED_BUSINESS_MESSAGES FULL JSON:\n%s", _full_json(event))


# ============================================================
# Helper: content type aniqlash
# ============================================================

def _detect_type(msg: Message) -> str:
    """Xabar content type'ini aniqlaydi."""
    if msg.text is not None:
        return "text"
    if msg.photo:
        return "photo"
    if msg.video:
        return "video"
    if msg.voice:
        return "voice"
    if msg.video_note:
        return "video_note"
    if msg.audio:
        return "audio"
    if msg.document:
        return "document"
    if msg.sticker:
        return "sticker"
    if msg.contact:
        return "contact"
    if msg.location:
        return "location"
    if msg.venue:
        return "venue"
    if msg.poll:
        return "poll"

    debug_logger.warning("⚠️ Unknown content_type for msg_id=%d", msg.message_id)
    return "unknown"


# ============================================================
# Ishga tushirish
# ============================================================

async def main() -> None:
    debug_logger.info("🚀 Debug bot starting... (no database, log only)")
    dp.include_router(router)

    # allowed_updates avtomatik aniqlanadi (resolve_used_update_types)
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())
