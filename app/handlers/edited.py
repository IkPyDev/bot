"""
edited_business_message handler — tahrirlangan xabar.

Mantiq:
1. Eski (tahrirdan oldingi) matnni bazadan olamiz.
2. Bildirishnoma tuzamiz: kim tahrirladi (ism + @username) + eski/yangi matn.
3. Kanalga yuboramiz (HAMMA tahrir — mijoznikimi, ownernikimi).
4. Owner ning shaxsiy chatiga yuboramiz — FAQAT mijoz (incoming) tahrirlaganda.
5. Eski xabarni is_edited=TRUE qilib belgilaymiz, yangi versiyani yozamiz.
"""

import html
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Router
from aiogram.types import Message, User

from app.db import db
from app.extractors import (
    detect_content_type,
    determine_direction,
    extract_media_fields,
    extract_text_or_caption,
)
from app.handlers.connection import connection_owners
from app.handlers.message import (
    _resolve_owner_id,
    chat_link_html,
    enqueue_channel_media,
    full_user_html,
    owner_link_html,
    send_owner_media,
)

router = Router(name="edited")
logger = logging.getLogger("bot.handlers.edited")


def _editor_label(user: Optional[User]) -> str:
    """Tahrirlagan/yozgan odam yorlig'i: 'Ism Familiya (@nik) [ID: 123]'."""
    if not user:
        return "Noma'lum"
    parts = [user.first_name or "", user.last_name or ""]
    label = " ".join(p for p in parts if p).strip() or "Noma'lum"
    if user.username:
        label += f" (@{user.username})"
    label += f" [ID: {user.id}]"
    return label


@router.edited_business_message()
async def on_edited_business_message(message: Message, bot: Bot) -> None:
    """Tahrirlangan business xabarni qayta ishlaydi."""

    connection_id = message.business_connection_id
    if not connection_id:
        return

    content_type = detect_content_type(message)
    from_user_id = message.from_user.id if message.from_user else None
    owner_id = await _resolve_owner_id(bot, connection_id)
    direction = determine_direction(from_user_id, owner_id)
    text = extract_text_or_caption(message, content_type)
    media = extract_media_fields(message, content_type)

    try:
        raw_json = json.loads(
            message.model_dump_json(exclude_none=True, by_alias=True)
        )
    except Exception:
        raw_json = {"error": "failed to serialize"}

    tg_date: Optional[datetime] = None
    if message.date:
        tg_date = message.date.replace(tzinfo=timezone.utc) if message.date.tzinfo is None else message.date

    from_user_name = None
    if message.from_user:
        parts = [message.from_user.first_name or ""]
        if message.from_user.username:
            parts.append(f"@{message.from_user.username}")
        from_user_name = " ".join(parts).strip() or None

    chat_id = message.chat.id if message.chat else 0

    text_preview = (text[:80] + "...") if text and len(text) > 80 else text
    logger.info(
        "[%s] edited_business_message | conn=%s chat=%d msg_id=%d type=%s | %s",
        direction.upper(),
        connection_id[:8],
        chat_id,
        message.message_id,
        content_type,
        text_preview or f"[{content_type}]",
        extra={
            "update_type": "edited_business_message",
            "connection_id": connection_id,
            "chat_id": chat_id,
            "from_user_id": from_user_id,
            "from_user_name": from_user_name,
            "direction": direction,
            "content_type": content_type,
            "text_preview": text_preview,
        },
    )

    # --- Eski (tahrirdan oldingi) versiyani bazadan olamiz (DB YOZUVIDAN OLDIN) ---
    old = await db.get_last_message(connection_id, chat_id, message.message_id)
    old_text = (old.get("text") if old else None) or "—"
    new_text = text or f"[{content_type}]"

    # --- Bildirishnoma tuzish ---
    # Kim tahrirladi — ismi bosiladigan havola (username bo'lsa t.me, bo'lmasa tg://user)
    u = message.from_user
    editor_name = None
    if u:
        editor_name = " ".join(p for p in [u.first_name or "", u.last_name or ""] if p).strip() or None
    editor = full_user_html(editor_name, u.username if u else None, u.id if u else None)

    chat_name = ""
    if message.chat:
        chat_name = (
            getattr(message.chat, "title", None)
            or getattr(message.chat, "first_name", None)
            or ""
        )
    when = message.date.strftime("%Y-%m-%d %H:%M:%S") if message.date else ""

    # HTML parse_mode ishlatilgani uchun matnlarni escape qilamiz
    old_e = html.escape(old_text)
    new_e = html.escape(new_text)

    # OWNER — soddaroq (Turi yo'q)
    owner_lines = ["✏️ Xabar tahrirlandi", f"👤 {editor}"]
    if chat_name:
        owner_lines.append(f"💬 Chat: {html.escape(chat_name)}")
    if when:
        owner_lines.append(f"🕐 {when}")
    header_owner = "\n".join(owner_lines)

    # Kimga (oluvchi): outgoing -> mijoz (chat), incoming -> owner
    if direction == "outgoing":
        kimga = chat_link_html(message.chat)
    else:
        kimga = owner_link_html(connection_id) or "?"

    # KANAL — TO'LIQ (kimdan -> kimga, ikkalasi bosiladigan havola)
    ch_lines = [
        "✏️ Xabar tahrirlandi",
        f"👤 Kimdan: {editor}",
        f"➡️ Kimga: {kimga}",
        f"🔀 Yo'nalish: {direction}",
        f"📎 Turi: {content_type}",
    ]
    if when:
        ch_lines.append(f"🕐 Tahrirlangan: {when}")
    header_channel = "\n".join(ch_lines)

    body = f"📝 Eski: {old_e}\n✅ Yangi: {new_e}"

    # Tahrirlangan yangi versiyaning mediasi (matn bo'lsa None)
    file_id = media["media_file_id"]

    # Kanalga — HAMMA tahrir (media bilan)
    enqueue_channel_media(content_type, file_id, header_channel, body)
    # Owner ning shaxsiy chatiga — FAQAT mijoz (incoming) tahrirlaganda
    if direction == "incoming":
        await send_owner_media(bot, connection_id, content_type, file_id, header_owner, body)

    # --- Bazaga yozish: eski versiyani belgilash + yangi versiyani qo'shish ---
    await db.mark_edited(
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message.message_id,
    )
    await db.insert_message(
        connection_id=connection_id,
        chat_id=chat_id,
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
        is_edited=True,
        raw_json=raw_json,
        tg_date=tg_date,
    )
