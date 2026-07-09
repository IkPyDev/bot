"""
business_connection handler — xodim botni uladi / o'chiradi / o'zgartiradi.

Mantiq:
1. Yangi ulanish → connections jadvaliga upsert.
2. is_enabled=false → o'chirilgan deb belgilanadi (tarix qoladi).
3. Owner user_id in-memory dict'ga saqlanadi (direction aniqlash uchun).
"""

import logging

from aiogram import Bot, Router
from aiogram.types import BusinessConnection

from app.config import settings
from app.db import db

router = Router(name="connection")
logger = logging.getLogger("bot.handlers.connection")

# Biznes akkaunt ulanganda yuboriladigan qo'llanma matni (video tagida caption).
CONNECT_CAPTION = (
    "✅ <b>Bot muvaffaqiyatli ulandi</b>\n\n"
    "<b>Qanday foydalanish kerak?</b>\n"
    "➖ Agar suhbatdoshingiz xabarni o'chirsa, bot darhol sizga o'sha xabar "
    "nusxasini yuboradi (faqat bot ulangandan KEYIN yuborilgan xabarlar bilan ishlaydi)\n"
    "➖ Taymerli surat/videolarni yuklab olish uchun, suhbatdoshingiz bilan dialogda "
    "ularga istalgan xabar bilan javob berishingiz kerak (videoda ☝️ misol ko'rsatilgan) "
    "(OCHISHDAN OLDIN, BU MUHIM!)\n\n"
    "❗ Bot faqat bot ulangandan keyin olingan YANGI xabarlar bilan ishlaydi"
)

# In-memory cache: connection_id → owner user_id
# Direction aniqlashda ishlatiladi
connection_owners: dict[str, int] = {}

# In-memory cache: connection_id → user_chat_id (eganing bot lichkasi)
# Xabarlarni forward qilish uchun
connection_user_chats: dict[str, int] = {}

# In-memory cache: connection_id → owner (egasi) ma'lumoti
# "Kimga" (incoming xabarda oluvchi = owner) ni ko'rsatish uchun
# {"id", "first_name", "last_name", "username"}
connection_owner_users: dict[str, dict] = {}


@router.business_connection()
async def on_business_connection(event: BusinessConnection, bot: Bot) -> None:
    """Business connection update'ini qayta ishlaydi."""

    # Owner user_id va user_chat_id ni cache'ga saqlash
    connection_owners[event.id] = event.user.id
    connection_owner_users[event.id] = {
        "id": event.user.id,
        "first_name": event.user.first_name,
        "last_name": getattr(event.user, "last_name", None),
        "username": event.user.username,
    }
    user_chat_id = getattr(event, "user_chat_id", None)
    if user_chat_id:
        connection_user_chats[event.id] = user_chat_id

    # can_reply — yangi versiyalarda rights bo'lishi mumkin
    can_reply = getattr(event, "can_reply", None)
    if can_reply is None:
        # rights mavjud bo'lsa, can_reply = True deb olamiz
        rights = getattr(event, "rights", None)
        can_reply = rights is not None

    # Logga chiqarish
    status = "ENABLED" if event.is_enabled else "DISABLED"
    logger.info(
        "Business connection %s: user=%d (@%s, %s) status=%s can_reply=%s",
        event.id,
        event.user.id,
        event.user.username or "",
        event.user.first_name or "",
        status,
        can_reply,
        extra={
            "update_type": "business_connection",
            "connection_id": event.id,
            "from_user_id": event.user.id,
            "from_user_name": event.user.first_name,
        },
    )

    # To'liq JSON log
    try:
        full_json = event.model_dump_json(
            indent=2, exclude_none=True, by_alias=True
        )
        logger.debug(
            "Full business_connection JSON:\n%s",
            full_json,
            extra={"update_type": "business_connection", "full_json": full_json},
        )
    except Exception:
        logger.debug("Could not serialize business_connection to JSON", exc_info=True)

    # Bazaga yozish (connections jadvali)
    await db.upsert_connection(
        connection_id=event.id,
        user_id=event.user.id,
        user_chat_id=getattr(event, "user_chat_id", None),
        username=event.user.username,
        first_name=event.user.first_name,
        can_reply=can_reply,
        is_enabled=event.is_enabled,
    )

    # bot_users jadvaliga ham saqlaymiz (reklama uchun)
    # Business connection ulagan user /start bosmasdan ham reklama olishi uchun
    if event.is_enabled:
        try:
            await db.upsert_bot_user(
                user_id=event.user.id,
                username=event.user.username,
                first_name=event.user.first_name,
                last_name=getattr(event.user, "last_name", None),
                language_code=getattr(event.user, "language_code", None),
            )
            logger.info(
                "Saved business connection user to bot_users: user_id=%d (@%s)",
                event.user.id,
                event.user.username or "",
            )
        except Exception as e:
            logger.warning("Failed to upsert bot_user from business connection: %s", e)

    # Tabriklash: "database" kanaldagi qo'llanma videosi + caption yuboramiz.
    if event.is_enabled:
        user_chat_id = getattr(event, "user_chat_id", None) or event.user.id
        try:
            if settings.media_channel_id and settings.connect_media_message_id:
                # copy_message file_id'ga bog'liq emas — har safar kanaldan o'qiydi (eskirmaydi).
                await bot.copy_message(
                    chat_id=user_chat_id,
                    from_chat_id=settings.media_channel_id,
                    message_id=settings.connect_media_message_id,
                    caption=CONNECT_CAPTION,
                )
            else:
                await bot.send_message(chat_id=user_chat_id, text=CONNECT_CAPTION)
            logger.info("Sent welcome message to user_chat_id=%s", user_chat_id)
        except Exception as e:
            # Video yuborilmasa (kanal/xabar topilmasa) — matn bilan urinib ko'ramiz
            logger.warning("Ulanish videosi yuborilmadi (user_chat_id=%s): %s — matn bilan", user_chat_id, e)
            try:
                await bot.send_message(chat_id=user_chat_id, text=CONNECT_CAPTION)
            except Exception as e2:
                logger.warning("Welcome matni ham yuborilmadi (user_chat_id=%s): %s", user_chat_id, e2)

