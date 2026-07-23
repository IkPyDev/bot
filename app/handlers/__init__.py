# Telegram Business Bot — handlers package

from aiogram import Router

from app.handlers.admin import router as admin_router
from app.handlers.connection import router as connection_router
from app.handlers.deleted import router as deleted_router
from app.handlers.edited import router as edited_router
from app.handlers.message import router as message_router
from app.handlers.start import router as start_router
from app.middlewares import LanguageMiddleware


def get_main_router() -> Router:
    """Barcha handlerlarni bitta router'ga yig'adi."""
    main_router = Router(name="main")

    # --- Til middleware (aiogram DI) ---
    # /start (message) va tugmalar (callback_query) handlerlariga `lang` uzatadi.
    # Faqat shu ikki turga ulaymiz — chunki bu yerda til = xabarni bosgan odamniki.
    # Business tahrir/o'chirish handlerlarida til OWNER'niki, ular o'zi aniqlaydi.
    lang_mw = LanguageMiddleware()
    start_router.message.middleware(lang_mw)
    start_router.callback_query.middleware(lang_mw)

    # Admin komandalari va FSM — eng birinchi (state handler ustuvor bo'lishi uchun)
    main_router.include_router(admin_router)

    # /start komandasi
    main_router.include_router(start_router)

    # Business update handlerlar
    main_router.include_router(connection_router)
    main_router.include_router(message_router)
    main_router.include_router(edited_router)
    main_router.include_router(deleted_router)
    return main_router

