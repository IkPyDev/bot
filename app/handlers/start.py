"""
/start komandasi handler — foydalanuvchi botga /start bosganda ishlaydi.

NIMA QILADI:
- /start bosganda xush kelibsiz xabari + video/rasm yuboradi
- Kanaldan olingan video file_id orqali yuboradi (har safar yuklamaydi!)

QANDAY FILE_ID OLISH:
1. Videoni shu botga yuborasiz (lichkaga)
2. Logda file_id chiqadi (konsolda ko'rasiz)
3. O'sha file_id ni pastdagi START_VIDEO_FILE_ID ga qo'yasiz
4. Bot endi har safar /start bosganda shu videoni yuboradi (tez, yuklamasdan)

O'ZGARTIRISH KERAK BO'LSA:
- START_VIDEO_FILE_ID — video uchun file_id qo'ying
- START_PHOTO_FILE_ID — rasm uchun file_id qo'ying
- START_TEXT — matn yozing
- on_start() funksiyasidagi kodlarni o'zgartiring
"""

import html
import json
import logging
from datetime import datetime, timezone
from aiogram import Bot, Router
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import FSInputFile

from app.config import settings
from app.db import db
from app.extractors import detect_content_type, extract_text_or_caption, extract_media_fields

router = Router(name="start")
logger = logging.getLogger("bot.handlers.start")


# ============================================================
# SOZLAMALAR — BU YERGA O'ZINGIZNING QIYMATLARNI YOZING
# ============================================================

# /start rasmi/videosi "database" kanalida turadi. Bot o'sha kanaldagi
# xabardan copy_message bilan olib, caption + tugma qo'shib yuboradi.
# Sozlash .env orqali:
#   START_MEDIA_CHAT_ID     = database kanal ID si (masalan -1004302584743)
#   START_MEDIA_MESSAGE_ID  = o'sha kanaldagi rasm/video xabar ID si (masalan 3)
# MUHIM: bot o'sha kanalning a'zosi/admini bo'lishi shart.
# Ikkalasi ham bo'sh bo'lsa — bot faqat matn (caption) yuboradi.

# Matn — /start bosganda chiqadigan matn
START_TEXT = (
    "Salom! 👋\n\n"
    "Men sizning business botingizman.\n"
    "Bu xabarni o'zgartirish uchun:\n"
    "📁 app/handlers/start.py faylini oching."
)

# Caption — rasm tagidagi matn (HTML formatida: bold / italic / blockquote / code).
# Bot default parse_mode="HTML" — teglar avtomatik render bo'ladi.
START_CAPTION = (
    "<b>🕵️‍♂️ Xush kelibsiz!</b>\n"
    "Men sizning yozishmalaringizni kuzatib turaman.\n\n"
    "<b>📌 Nima qila olaman:</b>\n\n"
    "🔔 Suhbatdoshingiz xabarini <b>tahrirlasa</b> — eski matnini ko'rsataman\n"
    "🗑 Xabarni <b>o'chirsa</b> — nima yozganini saqlab qolaman\n"
    "⏳ <b>Bir marta ko'riladigan</b> surat, video, ovozli xabar va yumoloq videolarni yuklab olaman\n\n"
    "➖➖➖➖➖➖➖➖➖\n\n"
    "<b>⚡️ Ishga tushirish — 3 ta oddiy qadam:</b>\n\n"
    "1️⃣ Pastdagi <b>«🔌 Ulash»</b> tugmasini bosing 👇\n\n"
    "2️⃣ Ochilgan oynadan <b>«Chatlarni avtomatlashtirish»</b> bo'limini tanlang 🤖\n\n"
    "3️⃣ Bo'sh maydonga bot nomini yozing 👇\n"
    "<code>@sirsaqlauzbot</code>\n"
    "Pastda bot chiqadi — <b>bot ustiga bosing</b> ✅\n\n"
    "➖➖➖➖➖➖➖➖➖\n\n"
)

# Inline tugmalar — /start xabari tagida chiqadi.
# "🔌 Ulash" tugmasi bosilganda Telegram sozlamalarini (business/edit) ochadi.
START_BUTTONS = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🔌 Ulash", url="tg://settings/edit"),
        ],
    ]
)


# ============================================================
# /start HANDLER
# ============================================================

@router.message(CommandStart())
async def on_start(message: Message, bot: Bot) -> None:
    """
    /start komandasi bosilganda ishlaydi.

    Kerakli variantni izohdan chiqaring (# olib tashlang).
    Bir nechta variantni aralashtirishingiz ham mumkin.
    """

    user = message.from_user
    user_name = user.first_name if user else "Foydalanuvchi"

    # --- 0. Foydalanuvchini bazaga saqlash (reklama yuborish uchun) ---
    # Har safar kimdir botga kirib /start bosa, uning ma'lumotlarini bazadagi `bot_users` jadvaliga yozib qo'yamiz.
    # Bu bizga keyinchalik barcha bot obunachilariga bitta bosishda reklama yuborish (/reklama komandasi orqali) imkonini beradi.
    if user:
        await db.upsert_bot_user(
            user_id=user.id,                    # Asosiy ID (bunga qarab yuboramiz)
            username=user.username,             # Kelajakda kimligini bilish uchun kerak
            first_name=user.first_name,         # Ismi
            last_name=user.last_name,           # Familiyasi
            language_code=user.language_code,   # Tili
        )

    # --- 0.1 /start xabarini o'zini ham bazaga (messages jadvaliga) yozib qo'yamiz ---
    try:
        raw_json = json.loads(message.model_dump_json(exclude_none=True))
        tg_date = message.date.replace(tzinfo=timezone.utc) if message.date else None
        await db.insert_message(
            connection_id=None,
            chat_id=message.chat.id,
            from_user_id=user.id if user else None,
            from_user_name=user_name,
            message_id=message.message_id,
            direction="incoming",
            content_type="text",
            text=message.text,
            media_file_id=None,
            media_file_name=None,
            media_mime=None,
            media_duration=None,
            is_edited=False,
            raw_json=raw_json,
            tg_date=tg_date,
        )
    except Exception as e:
        logger.error("Failed to insert /start message to db: %s", e)

    # ============================================================
    # DEFAULT SALOMLASHISH — RASM + FORMATLANGAN CAPTION
    # Matn/rasmni o'zgartirish uchun yuqoridagi START_CAPTION / START_PHOTO_FILE_ID.
    # ============================================================
    sent_msg = None
    sent_type = "text"
    try:
        if settings.media_channel_id and settings.start_media_message_id:
            # "database" kanaldagi rasm/videoni caption + tugma bilan nusxalab yuboramiz.
            # copy_message file_id'ga bog'liq emas — har safar kanaldan o'qiydi (eskirmaydi).
            sent_msg = await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=settings.media_channel_id,
                message_id=settings.start_media_message_id,
                caption=START_CAPTION,
                reply_markup=START_BUTTONS,
            )
            sent_type = "media"
        else:
            sent_msg = await message.answer(START_CAPTION, reply_markup=START_BUTTONS)
    except Exception as e:
        # Kanal/xabar topilmasa yoki bot a'zo bo'lmasa — matn bilan yuboramiz (bot to'xtamaydi)
        logger.warning("Start media yuborilmadi (%s) — matn bilan yuboramiz", e)
        sent_msg = await message.answer(START_CAPTION, reply_markup=START_BUTTONS)
        sent_type = "text"

    # --- 0.2 Bot yuborgan javobni ham bazaga yozamiz (AI analizi uchun outgoing) ---
    try:
        bot_me = await bot.me()  # aiogram natijani keshlaydi — har safar API chaqirmaydi
        bot_name = " ".join(
            p for p in [bot_me.first_name or "", f"@{bot_me.username}" if bot_me.username else ""] if p
        ).strip() or "Bot"
        await db.insert_message(
            connection_id=None,
            chat_id=message.chat.id,
            from_user_id=bot_me.id,
            from_user_name=bot_name,
            message_id=sent_msg.message_id if sent_msg else 0,
            direction="outgoing",
            content_type=sent_type,
            text=START_CAPTION,
            media_file_id=None,
            media_file_name=None,
            media_mime=None,
            media_duration=None,
            is_edited=False,
            raw_json={},
            tg_date=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.error("Failed to log outgoing greeting: %s", e)

    # ============================================================
    # VIDEO YUBORISH — kerak bo'lsa # ni olib tashlang
    #
    # FILE_ID OLISH USULLARI:
    #
    # 1-usul: KANALDAN OLISH
    #    - Kanaldan videoni shu botga forward qiling (lichkaga)
    #    - Bot javob beradi: 🎬 Video file_id: BAACAgIAAxkB...
    #    - O'sha file_id ni pastga qo'ying
    #
    # 2-usul: BOTGA TO'G'RIDAN-TO'G'RI YUBORISH
    #    - Botga lichka orqali video yuboring
    #    - Bot file_id qaytaradi
    #
    # 3-usul: URL ORQALI (har safar yuklab oladi — sekinroq)
    #    - video="https://example.com/video.mp4"
    #
    # MISOL (file_id bilan — tez, yuklamasdan):
    # await bot.send_video(
    #     chat_id=message.chat.id,
    #     video="BAACAgIAAxkBAAIBZ2X_MISOL_FILE_ID",
    #     caption="Video tagidagi matn",
    # )
    #
    # MISOL (URL bilan — sekin, har safar yuklab oladi):
    # await bot.send_video(
    #     chat_id=message.chat.id,
    #     video="https://example.com/video.mp4",
    #     caption="Video tagidagi matn",
    # )
    # ============================================================

    # ============================================================
    # RASM YUBORISH — kerak bo'lsa # ni olib tashlang
    # file_id ni olish: botga lichkadan rasm yuboring, bot file_id qaytaradi
    # ============================================================
    # await bot.send_photo(
    #     chat_id=message.chat.id,
    #     photo="BU_YERGA_RASM_FILE_ID_QOYING",
    #     caption="Rasm tagidagi matn",
    # )

    # ============================================================
    # MATN YUBORISH — kerak bo'lsa # ni olib tashlang
    # ============================================================
    # await message.answer("Bu yerga xohlagan matningizni yozing")

    # ============================================================
    # INLINE TUGMALAR — kerak bo'lsa # ni olib tashlang
    # ============================================================
    # keyboard = InlineKeyboardMarkup(
    #     inline_keyboard=[
    #         [
    #             InlineKeyboardButton(text="📞 Aloqa", url="https://t.me/your_username"),
    #             InlineKeyboardButton(text="🌐 Sayt", url="https://your-site.com"),
    #         ],
    #         [
    #             InlineKeyboardButton(text="📋 Xizmatlar", callback_data="services"),
    #         ],
    #     ]
    # )
    # await message.answer("Tanlang:", reply_markup=keyboard)

    # ============================================================
    # AUDIO YUBORISH — kerak bo'lsa # ni olib tashlang
    # ============================================================
    # await bot.send_audio(
    #     chat_id=message.chat.id,
    #     audio="BU_YERGA_AUDIO_FILE_ID_QOYING",
    #     caption="Audio tagidagi matn",
    # )

    # ============================================================
    # VOICE YUBORISH — kerak bo'lsa # ni olib tashlang
    # ============================================================
    # await bot.send_voice(
    #     chat_id=message.chat.id,
    #     voice="BU_YERGA_VOICE_FILE_ID_QOYING",
    # )

    # ============================================================
    # DOCUMENT YUBORISH — kerak bo'lsa # ni olib tashlang
    # ============================================================
    # await bot.send_document(
    #     chat_id=message.chat.id,
    #     document="BU_YERGA_DOCUMENT_FILE_ID_QOYING",
    #     caption="Fayl tagidagi matn",
    # )

    logger.info(
        "/start from user_id=%d (%s)",
        message.from_user.id if message.from_user else 0,
        user_name,
    )


# ============================================================
# FILE_ID NI OLISH UCHUN YORDAMCHI HANDLER
#
# Botga rasm/video yuborsangiz — file_id ni logga chiqaradi.
# O'sha file_id ni yuqoridagi START_VIDEO_FILE_ID yoki
# START_PHOTO_FILE_ID ga qo'yasiz.
#
# Bu handler faqat SHAXSIY chatda ishlaydi (business emas).
# ============================================================

@router.message()
async def on_private_message(message: Message) -> None:
    """
    Botga lichka orqali yuborilgan xabarni qayta ishlaydi.
    Maqsad: file_id ni olish (video, rasm, va h.k.) hamda bazaga saqlash.
    """

    # Business xabarlarni o'tkazib yuboramiz (ular message handler da ishlanadi)
    if message.business_connection_id:
        return

    # --- 0. BAZAGA SAQLASH (Lichkaga kelgan barcha xabarlar) ---
    content_type = detect_content_type(message)
    text = extract_text_or_caption(message, content_type)
    media_fields = extract_media_fields(message, content_type)
    
    # Xabarni JSON ko'rinishida olish (xatolik bo'lmasligi uchun default=str)
    raw_json = json.loads(message.model_dump_json(exclude_none=True))
    
    # Xabarning asl vaqti
    tg_date = message.date.replace(tzinfo=timezone.utc) if message.date else None
    
    # Bazaga yozamiz (connection_id = None qilib)
    await db.insert_message(
        connection_id=None,
        chat_id=message.chat.id,
        from_user_id=message.from_user.id if message.from_user else None,
        from_user_name=message.from_user.first_name if message.from_user else None,
        message_id=message.message_id,
        direction="incoming",  # Chunki mijoz/user botga yozdi
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
    logger.info("Saved private bot message to DB: user=%d, msg_id=%d", message.from_user.id if message.from_user else 0, message.message_id)

    # --- 1. RASM ---
    if message.photo:
        largest = message.photo[-1]
        logger.info("📷 PHOTO file_id: %s", largest.file_id)
        await message.reply(
            f"📷 Rasm file_id:\n\n"
            f"`{largest.file_id}`\n\n"
            f"Bu qiymatni start.py dagi\n"
            f"START_PHOTO_FILE_ID ga qo'ying.",
            parse_mode="Markdown",
        )
        return

    # --- VIDEO ---
    if message.video:
        logger.info("🎬 VIDEO file_id: %s", message.video.file_id)
        await message.reply(
            f"🎬 Video file_id:\n\n"
            f"`{message.video.file_id}`\n\n"
            f"Bu qiymatni start.py dagi\n"
            f"START_VIDEO_FILE_ID ga qo'ying.",
            parse_mode="Markdown",
        )
        return

    # --- STICKER ---
    if message.sticker:
        logger.info("🎨 STICKER file_id: %s", message.sticker.file_id)
        await message.reply(
            f"🎨 Sticker file_id:\n\n"
            f"`{message.sticker.file_id}`",
            parse_mode="Markdown",
        )
        return

    # --- DOCUMENT ---
    if message.document:
        logger.info("📎 DOCUMENT file_id: %s", message.document.file_id)
        await message.reply(
            f"📎 Document file_id:\n\n"
            f"`{message.document.file_id}`",
            parse_mode="Markdown",
        )
        return

    # --- VOICE ---
    if message.voice:
        logger.info("🎤 VOICE file_id: %s", message.voice.file_id)
        await message.reply(
            f"🎤 Voice file_id:\n\n"
            f"`{message.voice.file_id}`",
            parse_mode="Markdown",
        )
        return

    # --- VIDEO_NOTE ---
    if message.video_note:
        logger.info("⭕ VIDEO_NOTE file_id: %s", message.video_note.file_id)
        await message.reply(
            f"⭕ Video note file_id:\n\n"
            f"`{message.video_note.file_id}`",
            parse_mode="Markdown",
        )
        return
