"""
Admin: baza zaxirasi, bazani tiklash, loglar va Telegram update'lari (JSON).

BUYRUQLAR (faqat ADMIN_IDS dagilar uchun):
  /admin            — buyruqlar ro'yxati
  /backup           — bazaning hozirgi to'liq nusxasi (.sql.gz)
  /restore          — nusxa faylidan bazani tiklash (boshqa serverga ko'chish)
  /logs [sana]      — log fayli (sana bo'lmasa — bugungi, joriy)
  /json [sana]      — shu kun Telegram'dan kelgan hamma narsa, to'liq JSON
  /loglar           — serverda bor log kunlari

Sana: 18.09.2026 yoki 18_09_2026.
"""

import logging
import os
import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app import scheduler
from app.config import settings
from app.db import db

router = Router(name="backup")
logger = logging.getLogger("bot.handlers.backup")

# Bot API orqali bot yuklab oladigan fayl chegarasi
_TG_DOWNLOAD_MAX = 20 * 1024 * 1024

# Faqat adminlar — boshqalar uchun bu buyruqlar umuman ishlamaydi
router.message.filter(F.from_user.id.func(lambda uid: uid in settings.admin_ids))


class RestoreState(StatesGroup):
    waiting_file = State()     # admin nusxa faylini yuborishi kutilmoqda
    waiting_confirm = State()  # "/tasdiq" kutilmoqda


def _now_label() -> str:
    return datetime.now().strftime("%d_%m_%Y_%H-%M")


def _parse_day(arg: str | None) -> str | None:
    """'18.09.2026' / '18_09_2026' / '18-09-2026' -> '18_09_2026'. Bo'sh bo'lsa — bugun."""
    if not arg:
        return datetime.now().strftime("%d_%m_%Y")
    parts = re.split(r"[._\-/]", arg.strip())
    try:
        d, m, y = (int(p) for p in parts)
        return datetime(y, m, d).strftime("%d_%m_%Y")
    except (ValueError, TypeError):
        return None


def _days_hint() -> str:
    days = scheduler.list_log_days()[:10]
    if not days:
        return "Serverda log fayllari yo'q."
    return "Bor kunlar:\n" + "\n".join(f"• <code>{d.replace('_', '.')}</code>" for d in days)


# ============================================================
# /admin — yordam
# ============================================================

@router.message(Command("admin"))
async def on_admin_help(message: Message) -> None:
    await message.answer(
        "🛠 <b>Admin buyruqlari</b>\n\n"
        "🗄 /backup — bazaning hozirgi to'liq nusxasi\n"
        "♻️ /restore — nusxa fayldan bazani tiklash\n"
        "📄 /logs — bugungi log (yoki <code>/logs 17.09.2026</code>)\n"
        "🧾 /json — bugun Telegram'dan kelgan hamma narsa, to'liq JSON "
        "(yoki <code>/json 17.09.2026</code>)\n"
        "📅 /loglar — serverda bor log kunlari\n\n"
        "<blockquote>Har kuni 00:30 da log, baza nusxasi va JSON "
        "backup kanaliga o'zi ham yuboriladi.</blockquote>"
    )


# ============================================================
# /backup — bazaning hozirgi nusxasi
# ============================================================

@router.message(Command("backup"))
async def on_backup(message: Message, bot: Bot) -> None:
    wait = await message.answer("⏳ Baza nusxasi tayyorlanmoqda...")
    ok = await scheduler._backup_db(bot, message.chat.id, _now_label(), scheduler.tmp_dir())
    if ok:
        await wait.edit_text(
            "✅ Baza nusxasi tayyor (yuqoridagi fayl).\n\n"
            "Boshqa serverga ko'chirish uchun:\n"
            "1️⃣ Yangi serverda botni ishga tushiring\n"
            "2️⃣ Botga /restore yozing\n"
            "3️⃣ Shu faylni yuboring va /tasdiq bosing"
        )
    else:
        await wait.edit_text("❌ Nusxa olinmadi. Xato logga yozildi (/logs).")


# ============================================================
# /logs, /json, /loglar
# ============================================================

@router.message(Command("loglar"))
async def on_log_days(message: Message) -> None:
    await message.answer(_days_hint())


@router.message(Command("logs"))
async def on_logs(message: Message, bot: Bot, command: CommandObject) -> None:
    day = _parse_day(command.args)
    if not day or not os.path.exists(scheduler.log_path(day)):
        await message.answer(f"❌ Bu kun uchun log topilmadi.\n\n{_days_hint()}")
        return
    today = day == datetime.now().strftime("%d_%m_%Y")
    label = "joriy (hozirgacha)" if today else day
    await scheduler.send_file(bot, message.chat.id, scheduler.log_path(day), f"📄 Log — {label}")


@router.message(Command("json"))
async def on_json(message: Message, bot: Bot, command: CommandObject) -> None:
    day = _parse_day(command.args)
    if not day:
        await message.answer(f"❌ Sana noto'g'ri.\n\n{_days_hint()}")
        return
    wait = await message.answer("⏳ JSON tayyorlanmoqda...")
    count = await scheduler.send_updates_json(bot, message.chat.id, day)
    if count is None:
        await wait.edit_text(f"❌ Bu kun uchun log topilmadi.\n\n{_days_hint()}")
    else:
        await wait.delete()


# ============================================================
# /restore — bazani nusxa fayldan tiklash
# ============================================================

def _cleanup_file(path: str | None) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


@router.message(Command("restore"))
async def on_restore_start(message: Message, state: FSMContext) -> None:
    await state.set_state(RestoreState.waiting_file)
    await message.answer(
        "♻️ <b>Bazani tiklash</b>\n\n"
        "1️⃣ /backup orqali olingan faylni (<code>.sql.gz</code> yoki <code>.sql</code>) shu yerga yuboring\n"
        "2️⃣ Keyin /tasdiq bosasiz\n\n"
        "⚠️ Hozirgi bazadagi ma'lumot fayldagisi bilan <b>almashtiriladi</b>. "
        "Oldin hozirgi baza nusxasi sizga avtomatik yuboriladi.\n\n"
        "❌ Bekor qilish: /bekor"
    )


@router.message(Command(commands=["bekor", "cancel"]), RestoreState.waiting_file)
@router.message(Command(commands=["bekor", "cancel"]), RestoreState.waiting_confirm)
async def on_restore_cancel(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    _cleanup_file(data.get("path"))
    await state.clear()
    await message.answer("✅ Tiklash bekor qilindi. Baza o'zgarmadi.")


@router.message(RestoreState.waiting_file, F.document)
async def on_restore_file(message: Message, bot: Bot, state: FSMContext) -> None:
    doc = message.document
    name = doc.file_name or ""
    if not (name.endswith(".sql") or name.endswith(".sql.gz")):
        await message.answer("❌ Fayl <code>.sql.gz</code> yoki <code>.sql</code> bo'lishi kerak.")
        return
    if (doc.file_size or 0) > _TG_DOWNLOAD_MAX:
        await message.answer(
            "❌ Fayl 20 MB dan katta — bot uni Telegram'dan yuklab ololmaydi.\n\n"
            "Serverda qo'lda tiklang (fayl serverga ko'chirilgach):\n"
            "<code>gunzip -c FAYL.sql.gz | docker compose exec -T db "
            "psql -U USER -d DB -v ON_ERROR_STOP=1 --single-transaction</code>"
        )
        return
    path = os.path.join(scheduler.tmp_dir(), f"restore_upload{'.sql.gz' if name.endswith('.gz') else '.sql'}")
    await bot.download(doc, destination=path)
    await state.update_data(path=path)
    await state.set_state(RestoreState.waiting_confirm)
    await message.answer(
        f"📥 Fayl qabul qilindi: <code>{name}</code>\n\n"
        "Bazani shu fayl bilan almashtirish uchun /tasdiq bosing.\n"
        "❌ Bekor qilish: /bekor"
    )


@router.message(RestoreState.waiting_file)
async def on_restore_wrong(message: Message) -> None:
    await message.answer("📎 Iltimos, nusxa faylini yuboring yoki /bekor bosing.")


@router.message(Command("tasdiq"), RestoreState.waiting_confirm)
async def on_restore_confirm(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    path = data.get("path")
    await state.clear()
    if not path or not os.path.exists(path):
        await message.answer("❌ Fayl topilmadi. /restore dan qayta boshlang.")
        return

    try:
        # 1. Xavfsizlik uchun — hozirgi bazaning nusxasi adminga
        wait = await message.answer("⏳ 1/2: Hozirgi baza nusxasi olinmoqda (ehtiyot uchun)...")
        ok = await scheduler._backup_db(bot, message.chat.id, f"tiklashdan_oldin_{_now_label()}", scheduler.tmp_dir())
        if not ok:
            await wait.edit_text("❌ Hozirgi baza nusxasi olinmadi — tiklash to'xtatildi. Baza o'zgarmadi.")
            return

        # 2. Tiklash (bitta tranzaksiya — xato bo'lsa hech narsa o'zgarmaydi)
        await wait.edit_text("⏳ 2/2: Baza tiklanmoqda...")
        ok, err = await scheduler.restore_db(path)
        if not ok:
            await wait.edit_text(
                "❌ Tiklab bo'lmadi. Baza <b>o'zgarmadi</b>.\n\n"
                f"<blockquote>{err[-700:].replace('<', '&lt;').replace('>', '&gt;')}</blockquote>"
            )
            return

        await db.reset_pool()
        counts = await db.count_rows()
        logger.info("Admin %s bazani tikladi: %s", message.from_user.id, counts)
        await wait.edit_text(
            "✅ <b>Baza tiklandi!</b> Bot shu ma'lumotlar bilan davom etyapti.\n\n"
            f"💬 Xabarlar: {counts['messages']}\n"
            f"👥 Chatlar: {counts['chats']}\n"
            f"🔗 Ulanishlar: {counts['connections']}\n"
            f"🙋 Bot foydalanuvchilari: {counts['bot_users']}"
        )
    finally:
        _cleanup_file(path)
