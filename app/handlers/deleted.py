"""
deleted_business_messages handler — o'chirilgan xabar(lar).

MUHIM: Telegram o'chirish eventida NA kim o'chirganini, NA xabar matnini beradi —
faqat message_id lar keladi. Shuning uchun matnni BAZADAN (biz saqlaganidan) tiklaymiz.

Mantiq:
1. O'chirilgan message_id lar uchun bazadagi saqlangan versiyalarni olamiz.
2. Har biri uchun bildirishnoma: kim yozgan (ism + @username), vaqt, tur, matn.
3. Kanalga yuboramiz (HAMMA o'chirilgan xabar).
4. Owner ning shaxsiy chatiga yuboramiz — FAQAT mijoz (incoming) yozgan xabar o'chsa.
5. Bazada is_deleted=TRUE qilib belgilaymiz (tarix qoladi).
"""

import html
import logging
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.types import BusinessMessagesDeleted

from app.db import db
from app.handlers.message import (
    chat_link_html,
    enqueue_channel_media,
    enqueue_channel_text,
    full_user_html,
    owner_lang,
    owner_link_html,
    send_owner_media,
)
from app.i18n import t

router = Router(name="deleted")
logger = logging.getLogger("bot.handlers.deleted")


def _fmt_dt(value) -> str:
    """datetime yoki None ni chiroyli satrga aylantiradi (UTC+0 belgisi bilan)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S") + " (UTC+0)"
    return str(value) if value else "—"


@router.deleted_business_messages()
async def on_deleted_business_messages(event: BusinessMessagesDeleted, bot: Bot) -> None:
    """O'chirilgan business xabarlarni qayta ishlaydi."""

    connection_id = event.business_connection_id
    chat_id = event.chat.id if event.chat else 0
    message_ids = event.message_ids

    logger.info(
        "deleted_business_messages | conn=%s chat=%d | %d messages deleted: %s",
        connection_id[:8] if connection_id else "?",
        chat_id,
        len(message_ids),
        message_ids,
        extra={
            "update_type": "deleted_business_messages",
            "connection_id": connection_id,
            "chat_id": chat_id,
        },
    )

    if not (connection_id and message_ids):
        return

    # Owner (ulagan foydalanuvchi) tili — bildirishnomani o'z tilida beramiz.
    olang = owner_lang(connection_id)

    # Chat nomi (agar bo'lsa)
    chat_name = ""
    if event.chat:
        chat_name = (
            getattr(event.chat, "title", None)
            or getattr(event.chat, "first_name", None)
            or ""
        )

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + " (UTC+0)"

    # --- O'chirilgan xabarlarning saqlangan matnini bazadan tiklaymiz ---
    records = await db.get_messages_by_ids(connection_id, chat_id, message_ids)
    by_id = {r["message_id"]: r for r in records}

    for mid in message_ids:
        rec = by_id.get(mid)

        if rec is None:
            # Bazada topilmadi — lekin owner va chat ma'lumotlari bor, ularni ko'rsatamiz
            owner_html = owner_link_html(connection_id) or "Noma'lum egasi"
            chat_html = chat_link_html(event.chat) if event.chat else (html.escape(chat_name) if chat_name else str(chat_id))
            notif = (
                f"🗑 Xabar o'chirildi\n"
                f"👤 Egasi (bot ulangan): {owner_html}\n"
                f"💬 Chat (kim bilan): {chat_html}\n"
                f"📌 Xabar ID: {mid}\n"
                f"🕐 O'chirilgan vaqt: {now_str}\n"
                f"⚠️ Xabar matni bazada topilmadi (bot ulanishdan oldin yuborilgan bo'lishi mumkin)"
            )
            enqueue_channel_text(notif)
            continue

        # Kim yozgan — ismi bosiladigan havola (username bo'lsa t.me, bo'lmasa tg://user)
        sender_name = rec.get("from_first_name") or rec.get("from_user_name") or "Noma'lum"
        sender = full_user_html(sender_name, rec.get("from_username"), rec.get("from_user_id"))

        ctype = rec.get("content_type") or "text"
        file_id = rec.get("media_file_id")
        rdir = rec.get("direction") or "?"
        # text ustuni: matn yoki (media uchun) caption
        body_channel = f"Matn: {html.escape(rec['text'])}" if rec.get("text") else ""
        body_owner = (
            f"{t(olang, 'n_label_text')} {html.escape(rec['text'])}" if rec.get("text") else ""
        )

        # Kimga (oluvchi): outgoing -> mijoz (chat), incoming -> owner
        if rdir == "outgoing":
            kimga = chat_link_html(event.chat)
        else:
            kimga = owner_link_html(connection_id) or "?"

        # OWNER — soddaroq (Turi yo'q), owner tilida (topilmasa inglizcha)
        owner_lines = [t(olang, "n_del_title"), f"👤 {sender}"]
        if chat_name:
            owner_lines.append(f"{t(olang, 'n_label_chat')} {html.escape(chat_name)}")
        owner_lines.append(f"{t(olang, 'n_del_deleted_at')} {now_str}")
        owner_lines.append(f"{t(olang, 'n_del_sent_at')} {_fmt_dt(rec.get('tg_date'))}")
        header_owner = "\n".join(owner_lines)

        # KANAL — TO'LIQ (kimdan -> kimga, ikkalasi bosiladigan havola) — admin logi (o'zbekcha)
        ch_lines = [
            "🗑 Xabar o'chirildi",
            f"👤 Kimdan: {sender}",
            f"➡️ Kimga: {kimga}",
            f"🔀 Yo'nalish: {rdir}",
            f"📎 Turi: {ctype}",
            f"🕐 O'chirilgan vaqt: {now_str}",
            f"🕐 Yuborilgan vaqt: {_fmt_dt(rec.get('tg_date'))}",
        ]
        header_channel = "\n".join(ch_lines)

        # Kanalga — HAMMA o'chirilgan xabar (media bilan, bazadagi file_id orqali) — admin logi o'zbekcha
        enqueue_channel_media(ctype, file_id, header_channel, body_channel)
        # Owner ning shaxsiy chatiga — FAQAT mijoz (incoming) yozgan xabar o'chsa, owner tilida
        if rec.get("direction") == "incoming":
            await send_owner_media(bot, connection_id, ctype, file_id, header_owner, body_owner)

    # --- Bazada belgilash ---
    await db.mark_deleted(
        connection_id=connection_id,
        chat_id=chat_id,
        message_ids=message_ids,
    )
