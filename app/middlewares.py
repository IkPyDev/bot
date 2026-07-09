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
from aiogram.types import Update

logger = logging.getLogger("bot.raw")


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
