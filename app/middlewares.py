"""
RawUpdateLogMiddleware — HAR QANDAY kelgan Update ni TO'LIQ logga chiqaradi.

MAQSAD: Telegram aynan qanday ma'lumot yuborishini (har bir update turi uchun:
message, edited_business_message, deleted_business_messages, business_connection, ...)
XOM holatda ko'rish. Har update handlerlarga borishidan OLDIN bir marta loglanadi.

Bu outer middleware — Dispatcher darajasida ishlaydi, ya'ni FILTRLARDAN OLDIN,
shuning uchun bot ushlagan har bir update bu yerdan o'tadi.
"""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, User

from app.i18n import pick_lang

logger = logging.getLogger("bot.raw")


# ============================================================
# TIL MIDDLEWARE — foydalanuvchi tilini bir marta aniqlab, handlerlarga uzatadi
# ============================================================
#
# MUAMMO: ilgari har bir handler o'zi tilni aniqlardi:
#     lang = pick_lang(message.from_user.language_code)   # /start da
#     lang = pick_lang(callback.from_user.language_code)  # tugmada
# Bu takror kod edi — har joyda bir xil satr.
#
# YECHIM (aiogram uslubi — "Dependency Injection"):
# 1. Middleware har update kelganda tilni BIR MARTA aniqlaydi.
# 2. Uni `data["lang"]` ga qo'yadi.
# 3. Handler shunchaki `lang` parametrini so'raydi — aiogram uni avtomatik
#    uzatadi. Ya'ni:
#        async def on_start(message: Message, bot: Bot, lang: str):
#                                                        ^^^^^^^^^ shu yerga keladi
#    endi handler ichida pick_lang(...) chaqirish shart emas.
#
# QAYERDA ISHLAYDI: bu middleware faqat `message` va `callback_query` uchun
# ulanadi (app/handlers/__init__.py da) — chunki o'sha update'larda
# `event_from_user` = matnni oladigan odam. Business tahrir/o'chirish
# handlerlarida esa til OWNER'niki bo'lishi kerak (xabar yuboruvchi emas),
# shuning uchun ular tilni o'zi aniqlaydi (owner_lang) — bu middleware ularга ulanmaydi.


class LanguageMiddleware(BaseMiddleware):
    """Foydalanuvchi tilini aniqlab, handlerlarga `lang` sifatida uzatadi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # `event_from_user` — aiogram har update uchun avtomatik to'ldiradigan
        # maydon (xabar/tugmani yuborgan foydalanuvchi). Inner middleware
        # bosqichida u allaqachon tayyor bo'ladi.
        user: User | None = data.get("event_from_user")

        # Telegram tilidan (masalan "ru", "en-US") bizning til kodimizni olamiz.
        # Topilmasa yoki qo'llab-quvvatlanmasa — pick_lang inglizchaga tushiradi.
        data["lang"] = pick_lang(user.language_code if user else None)

        # Update'ni odatdagidek handlerga uzatamiz (endi `lang` data ichida)
        return await handler(event, data)


class RawUpdateLogMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        # Qaysi tur ekanligini aniqlash (message / edited_business_message / ...)
        try:
            etype = event.event_type
        except Exception:
            etype = "?"

        # Butun update ni AYNAN Telegram yuborgan JSON ko'rinishida olamiz.
        #   by_alias=True  -> Telegram nomlari bilan (masalan "from", "chat")
        #   exclude_none   -> bo'sh (null) maydonlarni tashlaymiz (shovqin kamaysin)
        # dict (struktura sifatida) + string (bitta qatorda to'liq ko'rinishi) — ikkisi ham
        try:
            full_dict = event.model_dump(mode="json", exclude_none=True, by_alias=True)
        except Exception:
            full_dict = {}
        try:
            full_str = event.model_dump_json(exclude_none=True, by_alias=True)
        except Exception:
            full_str = "{}"

        logger.info(
            "RAW UPDATE [%s] id=%s | %s",
            etype,
            getattr(event, "update_id", "?"),
            full_str,  # <-- BUTUN update JSON shu qatorda (grep bilan ham to'liq)
            extra={
                "update_type": "raw_update",
                "event_type": etype,
                "raw_update": full_dict,  # <-- struktura sifatida (nested)
            },
        )

        # Update ni odatdagidek handlerlarga uzatamiz
        return await handler(event, data)
