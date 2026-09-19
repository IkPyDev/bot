"""
Kanal hovuzi — xabar nusxalari bir nechta kanalga taqsimlanadi.

QANDAY ISHLAYDI:
- Asosiy kanal (.env CHANNEL_ID) doim ishlaydi.
- Admin botni istalgan kanalga ADMIN qilib qo'shsa (xabar yuborish huquqi bilan) —
  kanal avtomatik hovuzga qo'shiladi va bazaga yoziladi.
- Bot kanaldan chiqarilsa yoki huquqi olinsa — hovuzdan chiqariladi.
- Bir kanal flood limitga tushsa, xabar boshqa kanal orqali ketadi.

XAVFSIZLIK: botni faqat ADMIN_IDS dagilar qo'shgan kanal qabul qilinadi.
Begona odam qo'shsa — bot kanaldan chiqib ketadi (mijoz xabarlari begona kanalga ketmasin).

/kanallar — ro'yxat (nomi, holati, nechta yuborilgan), yoqish/o'chirish tugmalari.
"""

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import settings
from app.db import db
from app.handlers import message as mh

router = Router(name="channels")
logger = logging.getLogger("bot.handlers.channels")


def _is_admin(user_id) -> bool:
    return user_id in settings.admin_ids


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.warning("Adminga xabar yuborilmadi: %s", admin_id)


def _chat_label(title, username, chat_id) -> str:
    label = f"<b>{html.escape(title or 'Nomsiz')}</b>"
    if username:
        label += f" @{html.escape(username)}"
    return f"{label} [<code>{chat_id}</code>]"


# ============================================================
# Bot kanalga qo'shildi / chiqarildi
# ============================================================

@router.my_chat_member(F.chat.type == "channel")
async def on_bot_channel_status(event: ChatMemberUpdated, bot: Bot) -> None:
    chat = event.chat
    if chat.id in (settings.channel_id, settings.backup_channel_id):
        return  # asosiy va backup kanal .env orqali boshqariladi

    new = event.new_chat_member
    can_post = new.status == "creator" or (
        new.status == "administrator" and getattr(new, "can_post_messages", False)
    )
    who = event.from_user
    who_label = f"{html.escape(who.full_name)} [<code>{who.id}</code>]" if who else "?"
    label = _chat_label(chat.title, chat.username, chat.id)

    if can_post:
        if not (who and _is_admin(who.id)):
            # Begona odam qo'shdi — mijoz xabarlari u yerga ketmasin
            logger.warning("Begona odam (%s) botni kanalga qo'shdi: %s — chiqib ketildi", who and who.id, chat.id)
            try:
                await bot.leave_chat(chat.id)
            except Exception:
                pass
            await _notify_admins(
                bot,
                f"⚠️ Begona odam botni kanalga admin qildi, bot chiqib ketdi.\n\n"
                f"📢 Kanal: {label}\n👤 Kim: {who_label}",
            )
            return
        await db.upsert_channel(chat.id, chat.title, chat.username, True, who.id)
        mh.add_channel_worker(bot, chat.id, chat.title)
        await _notify_admins(
            bot,
            f"✅ Yangi kanal qo'shildi: {label}\n\n"
            f"Endi xabar nusxalari shu kanalga ham boradi.\n"
            f"📡 Ishlayotgan kanallar: {len(mh._channel_workers)} ta — /kanallar",
        )
    else:
        await db.upsert_channel(chat.id, chat.title, chat.username, False, None)
        removed = await mh.remove_channel_worker(chat.id)
        if removed:
            await _notify_admins(
                bot,
                f"❌ Kanal olib tashlandi: {label}\n"
                f"(bot chiqarildi yoki xabar yuborish huquqi olindi)\n\n"
                f"📡 Ishlayotgan kanallar: {len(mh._channel_workers)} ta",
            )


# ============================================================
# /kanallar — ro'yxat va boshqaruv (faqat admin)
# ============================================================

async def _channels_view(bot: Bot) -> tuple[str, InlineKeyboardMarkup]:
    loop = asyncio.get_running_loop()
    rows_db = await db.get_channels()

    # Asosiy kanal + bazadagilar
    items = []
    main_id = settings.channel_id
    if main_id:
        st = mh.channel_state.get(main_id, {})
        title = st.get("title")
        if not title:
            try:
                ch = await bot.get_chat(main_id)
                title = ch.title
                if st:
                    st["title"] = title
            except Exception:
                title = None
        items.append({"chat_id": main_id, "title": title, "username": None, "is_active": True, "main": True})
    items += [dict(r, main=False) for r in rows_db]

    lines = [f"📡 <b>Kanallar</b> — ishlayapti: {len(mh._channel_workers)} ta"]
    lines.append(f"📥 Navbatda kutayotgan: {mh.channel_queue_size()} ta\n")
    kb = []
    for i, it in enumerate(items, 1):
        cid = it["chat_id"]
        st = mh.channel_state.get(cid, {})
        working = mh.is_channel_working(cid)
        flood_left = int(st.get("flood_until", 0) - loop.time())
        if working and flood_left > 0:
            status = f"⏸ flood, {flood_left}s dam olyapti"
        elif working:
            status = "✅ ishlayapti"
        elif st.get("error"):
            status = f"⚠️ xato: {html.escape(st['error'][:80])}"
        else:
            status = "⛔️ o'chirilgan"
        star = "⭐ " if it["main"] else ""
        line = (
            f"{i}. {star}{_chat_label(it['title'], it['username'], cid)}\n"
            f"    {status} · yuborildi: {st.get('sent', 0)}"
        )
        if sum(len(x) for x in lines) + len(line) < 3300:  # Telegram 4096 chegarasi
            lines.append(line)
        elif not lines[-1].startswith("…"):
            lines.append(f"… yana {len(items) - i + 1} ta kanal (tugmalarda)")
        name = (it["title"] or str(cid))[:25]
        if working and not it["main"]:
            kb.append([InlineKeyboardButton(text=f"⛔️ O'chirish: {name}", callback_data=f"ch:off:{cid}")])
        elif not working:
            kb.append([InlineKeyboardButton(text=f"✅ Yoqish: {name}", callback_data=f"ch:on:{cid}")])
    kb.append([InlineKeyboardButton(text="🔄 Yangilash", callback_data="ch:ref:0")])

    lines.append(
        "\n<blockquote>➕ Kanal qo'shish:\n"
        "1️⃣ Yangi kanal oching\n"
        "2️⃣ Botni kanalga admin qiling (xabar yuborish huquqi bilan)\n"
        "3️⃣ Tamom — bot o'zi qo'shadi va sizga xabar beradi</blockquote>"
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb[:-1][:99] + kb[-1:])  # max 100 tugma


@router.message(Command("kanallar"), F.from_user.id.func(_is_admin))
async def on_channels(message: Message, bot: Bot) -> None:
    text, kb = await _channels_view(bot)
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("ch:"), F.from_user.id.func(_is_admin))
async def on_channels_action(call: CallbackQuery, bot: Bot) -> None:
    _, action, value = call.data.split(":", 2)
    cid = int(value)
    if action == "off":
        await mh.remove_channel_worker(cid)
        await db.set_channel_active(cid, False)
        await call.answer("⛔️ Kanal o'chirildi — endi unga xabar bormaydi")
    elif action == "on":
        try:
            ch = await bot.get_chat(cid)
            me = await bot.get_chat_member(cid, bot.id)
            ok = me.status == "creator" or getattr(me, "can_post_messages", False)
        except Exception:
            ch, ok = None, False
        if not ok:
            await call.answer("❌ Bot bu kanalda admin emas yoki yozish huquqi yo'q", show_alert=True)
            return
        is_main = cid == settings.channel_id
        if not is_main:
            await db.upsert_channel(cid, ch.title, ch.username, True, call.from_user.id)
        mh.add_channel_worker(bot, cid, ch.title, main=is_main)
        await call.answer("✅ Kanal yoqildi")
    else:
        await call.answer()
    text, kb = await _channels_view(bot)
    try:
        await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest:
        pass  # "message is not modified"
