"""
Telegram Business Bot — Production rejim.

To'rtala business update turini ushlab, SQLite ga saqlaydi.
Bot hech kimga javob YOZMAYDI.

Ishga tushirish:
    python main.py
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.db import db
from app.handlers import get_main_router
from app.handlers.message import start_channel_worker, stop_channel_worker
from app.logger import setup_logger, stop_logging
from app.middlewares import RawUpdateLogMiddleware
from app.scheduler import start_scheduler, stop_scheduler

# ---- Logging ----
main_logger = setup_logger(
    name="bot",
    level=settings.log_level,
    log_file=settings.log_file,
)

# aiogram o'z loglarini kamaytirish
logging.getLogger("aiogram").setLevel(logging.WARNING)


async def on_startup(bot: Bot) -> None:
    """Bot ishga tushganda: bazaga ulanish."""
    await db.connect(settings.database_url)
    main_logger.info("Bot started successfully. PostgreSQL connected.")

    # Kanal forward workerini ishga tushirish (agar kanal sozlangan bo'lsa)
    if settings.channel_id:
        start_channel_worker(bot, settings.channel_id)

    # Kunlik backup scheduler (kechagi log + DB dump -> backup kanaliga)
    start_scheduler(bot)

    # Bot ma'lumotlarini logga chiqarish
    try:
        me = await bot.get_me()
        main_logger.info(
            "Bot info: id=%d, username=@%s, name=%s",
            me.id,
            me.username or "",
            me.first_name or "",
        )
    except Exception:
        main_logger.warning("Could not fetch bot info", exc_info=True)


async def on_shutdown(bot: Bot) -> None:
    """Bot to'xtaganda: workerni to'xtatish, bazani yopish, logni flush qilish."""
    await stop_scheduler()
    await stop_channel_worker()
    await db.close()
    main_logger.info("Bot stopped. Database disconnected.")
    # Logging listener thread ni oxirida to'xtatamiz (navbatdagi loglar flush bo'lsin)
    stop_logging()


async def main() -> None:
    """Asosiy funksiya — dispatcher va polling."""
    # default parse_mode=HTML — bildirishnomalardagi 👤 havolalari ishlashi uchun
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Har qanday update ni to'liq logga chiqaruvchi middleware (eng birinchi)
    dp.update.outer_middleware(RawUpdateLogMiddleware())

    # Handlerlarni ulash
    main_router = get_main_router()
    dp.include_router(main_router)

    main_logger.info("🚀 Production bot starting (polling mode)...")

    try:
        # allowed_updates avtomatik — registratsiya qilingan handlerlar bo'yicha
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            # Bir vaqtda ishlaydigan handler tasklar soni cheklovi (backpressure).
            # Xabar to'lqini kelsa ham cheksiz task/RAM portlashi bo'lmaydi.
            tasks_concurrency_limit=100,
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
