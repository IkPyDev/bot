"""
Admin handler — reklama yuborish (FSM state-based).

QANDAY ISHLAYDI:
1. Admin /reklama yozadi
2. Bot adminni "reklama_mode" statega soladi
3. Admin istagan xabarni (matn, rasm, video, va h.k.) yuboradi
4. Bot o'sha xabarni barcha bot_users ga copy_message orqali tarqatadi
5. State tozalanadi (admin normal rejimga qaytadi)

BEKOR QILISH:
- /bekor yoki /cancel yozsa — state tozalanadi, hech narsa yuborilmaydi

ADMIN SOZLASH:
- .env da ADMIN_IDS=123456789,987654321 ko'rinishida yozing
"""

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.config import settings
from app.db import db
from app.extractors import detect_content_type, extract_media_fields, extract_text_or_caption

router = Router(name="admin")
logger = logging.getLogger("bot.handlers.admin")


# ============================================================
# FSM STATLAR — admin qaysi rejimda ekanligini belgilaydi
# ============================================================

class BroadcastState(StatesGroup):
    waiting_for_message = State()   # Admin reklama xabarini kutayapti


# ============================================================
# YORDAMCHI: admin tekshiruvi
# ============================================================

def is_admin(user_id: int) -> bool:
    """Foydalanuvchi admin ekanligini tekshiradi."""
    return user_id in settings.admin_ids


# ============================================================
# 1. /reklama — adminni state ga soladi
# ============================================================

@router.message(Command(commands=["reklama", "send", "broadcast"]))
async def on_broadcast_start(message: Message, state: FSMContext) -> None:
    """
    /reklama bosilganda adminni 'reklama_mode' statega soladi.
    Keyingi xabar reklama sifatida tarqatiladi.
    """
    user_id = message.from_user.id if message.from_user else 0

    # Admin tekshiruvi
    if not is_admin(user_id):
        return  # Admin emas — e'tibor bermaymiz

    # Bazada userlar bormi?
    users = await db.get_all_bot_users()
    if not users:
        await message.answer("⚠️ Hozircha bazada foydalanuvchilar yo'q.\n\nKimdir /start bosishi kerak.")
        return

    # Adminni state ga solamiz
    await state.set_state(BroadcastState.waiting_for_message)

    await message.answer(
        f"📢 <b>Reklama rejimi yoqildi!</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{len(users)} ta</b>\n\n"
        f"Endi reklama xabarini yuboring (matn, rasm, video, sticker — istalgan tur).\n\n"
        f"❌ Bekor qilish uchun /bekor yozing.",
        parse_mode="HTML",
    )
    logger.info("Admin %d entered broadcast state (users count: %d)", user_id, len(users))


# ============================================================
# 2. /bekor — state ni bekor qiladi
# ============================================================

@router.message(Command(commands=["bekor", "cancel"]), BroadcastState.waiting_for_message)
async def on_broadcast_cancel(message: Message, state: FSMContext) -> None:
    """Admin reklama rejimini bekor qiladi."""
    await state.clear()
    await message.answer("✅ Reklama bekor qilindi. Normal rejimga qaytdingiz.")
    logger.info("Admin %d cancelled broadcast", message.from_user.id if message.from_user else 0)


# ============================================================
# 3. Reklama xabari — state da turgan admin xabar yuborganda
# ============================================================

@router.message(BroadcastState.waiting_for_message)
async def on_broadcast_message(message: Message, bot: Bot, state: FSMContext) -> None:
    """
    Admin reklama_mode state da xabar yuborganda — shu xabarni
    barcha bot_users ga copy_message orqali tarqatadi.
    """
    user_id = message.from_user.id if message.from_user else 0

    # State ni darhol tozalaymiz (takroriy yuborishni oldini olish uchun)
    await state.clear()

    # Barcha userlarni bazadan olamiz
    users = await db.get_all_bot_users()
    if not users:
        await message.answer("⚠️ Foydalanuvchilar bazasi bo'sh.")
        return

    # Boshlash xabari
    status_msg = await message.answer(
        f"🚀 <b>Reklama yuborilmoqda...</b>\n"
        f"👥 Jami: <b>{len(users)} ta</b> foydalanuvchi",
        parse_mode="HTML",
    )

    # --------------------------------------------------------
    # Xabarni hammaga yuborish (broadcast)
    # --------------------------------------------------------
    success_count = 0
    fail_count = 0
    blocked_users = []  # Botni bloklagan userlar

    for uid in users:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            success_count += 1
        except Exception as e:
            err_str = str(e).lower()
            # Botni bloklagan yoki chat topilmagan userlarni aniqlaymiz
            if "blocked" in err_str or "not found" in err_str or "deactivated" in err_str:
                blocked_users.append(uid)
            logger.warning("Broadcast failed for user %d: %s", uid, e)
            fail_count += 1

        # Telegram flood limit: ~30 msg/sec → 0.05s pauza
        await asyncio.sleep(0.05)

    # --------------------------------------------------------
    # DB ga reklama xabarini yozib qo'yamiz (statistika uchun)
    # --------------------------------------------------------
    try:
        content_type = detect_content_type(message)
        text = extract_text_or_caption(message, content_type)
        media_fields = extract_media_fields(message, content_type)
        import json
        from datetime import datetime, timezone
        raw_json = json.loads(message.model_dump_json(exclude_none=True))
        tg_date = datetime.now(timezone.utc)

        # Muvaffaqiyatli borlagan har bir user uchun DB ga yozamiz
        for uid in users:
            if uid not in blocked_users:
                await db.insert_message(
                    connection_id=None,
                    chat_id=uid,
                    from_user_id=user_id,
                    from_user_name="Admin (Broadcast)",
                    message_id=message.message_id,
                    direction="outgoing",
                    content_type=content_type,
                    text=text,
                    media_file_id=media_fields["media_file_id"],
                    media_file_name=media_fields["media_file_name"],
                    media_mime=media_fields["media_mime"],
                    media_duration=media_fields["media_duration"],
                    is_edited=False,
                    raw_json=raw_json,
                    tg_date=tg_date,
                )
    except Exception as e:
        logger.error("Failed to log broadcast to DB: %s", e)

    # --------------------------------------------------------
    # Yakuniy natija
    # --------------------------------------------------------
    result_text = (
        f"✅ <b>Reklama tugadi!</b>\n\n"
        f"📨 Muvaffaqiyatli: <b>{success_count} ta</b>\n"
        f"❌ Xatolik: <b>{fail_count} ta</b>"
    )
    if blocked_users:
        result_text += f"\n🚫 Bot bloklagan: <b>{len(blocked_users)} ta</b>"

    # Status xabarini yangilaymiz
    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=result_text,
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(result_text, parse_mode="HTML")

    logger.info(
        "Broadcast done by admin %d. Success: %d, Fail: %d",
        user_id, success_count, fail_count,
    )
