"""
Kunlik backup rejalashtiruvchi (scheduler).

Har kuni belgilangan vaqtda (default 00:30, MAHALLIY vaqt):
  1. KECHAGI kunning log faylini (gzip) backup kanaliga yuboradi.
  2. PostgreSQL bazasini `pg_dump` qilib (gzip) backup kanaliga yuboradi.

MUHIM:
- Log fayllari serverda QOLADI (o'chirilmaydi) — foydalanuvchi o'zi tozalaydi.
- Log rotatsiyasini logger.py bajaradi (TimedRotatingFileHandler, har yarim tunda).
  Bu yerda faqat kechagi rotatsiya qilingan faylni topib, kanalga yuboramiz.
- `pg_dump` server PATH da bo'lishi kerak (postgresql-client).
- Telegram bot API bitta faylni max 50 MB gacha yuboradi — undan katta bo'lsa
  ogohlantirish yuboriladi (gzip odatda JSON logni ~10x kichraytiradi).
"""

import asyncio
import gzip
import logging
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import settings

logger = logging.getLogger("bot.scheduler")

# Telegram bot API send_document limiti
_TG_MAX = 50 * 1024 * 1024

_task: Optional[asyncio.Task] = None


def _parse_hhmm(value: str) -> tuple[int, int]:
    """'HH:MM' -> (hour, minute). Noto'g'ri bo'lsa 00:30 qaytaradi."""
    try:
        h_str, m_str = value.strip().split(":")
        h = max(0, min(23, int(h_str)))
        m = max(0, min(59, int(m_str)))
        return h, m
    except Exception:
        return 0, 30


def _seconds_until(hour: int, minute: int) -> float:
    """Keyingi HH:MM (mahalliy vaqt) gacha necha soniya qolganini qaytaradi."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _gzip_file(src: str, dst: str) -> None:
    """Faylni gzip qiladi (BLOKLOVCHI — executor da chaqiriladi)."""
    with open(src, "rb") as f_in, gzip.open(dst, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


async def _send_document(bot: Bot, channel_id: int, path: str, caption: str) -> None:
    """Faylni kanalga yuboradi; 50 MB dan katta bo'lsa ogohlantiradi."""
    size = os.path.getsize(path)
    if size > _TG_MAX:
        logger.error("Fayl 50MB dan katta (%d bayt), yuborilmadi: %s", size, path)
        await bot.send_message(
            channel_id,
            f"⚠️ {caption}\nFayl 50 MB dan katta ({size // 1024 // 1024} MB) — "
            f"Telegram orqali yuborib bo'lmadi.",
        )
        return
    await bot.send_document(channel_id, FSInputFile(path), caption=caption)


async def _backup_logs(bot: Bot, channel_id: int, day: str, tmp_dir: str) -> None:
    """Kechagi rotatsiya qilingan logni (logs/log_<day>.log) gzip qilib yuboradi."""
    log_dir = os.path.dirname(settings.log_file) or "."
    rotated = os.path.join(log_dir, f"log_{day}.log")
    if not os.path.exists(rotated):
        logger.warning("Kechagi log fayli topilmadi: %s", rotated)
        return
    gz_path = os.path.join(tmp_dir, f"log_{day}.log.gz")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _gzip_file, rotated, gz_path)
    try:
        await _send_document(bot, channel_id, gz_path, f"📄 Log — {day}")
        logger.info("Kechagi log kanalga yuborildi: %s", day)
    finally:
        _safe_remove(gz_path)


async def _backup_db(bot: Bot, channel_id: int, day: str, tmp_dir: str) -> None:
    """PostgreSQL ni pg_dump qilib, gzip qilib kanalga yuboradi."""
    dump_path = os.path.join(tmp_dir, f"db-{day}.sql")
    gz_path = dump_path + ".gz"

    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            "--dbname", settings.database_url,
            "--no-owner",
            "--no-privileges",
            "-f", dump_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("pg_dump topilmadi — postgresql-client o'rnatilmagan. DB backup o'tkazib yuborildi.")
        return

    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(
            "pg_dump xato (code=%s): %s",
            proc.returncode,
            (stderr or b"").decode(errors="replace")[:500],
        )
        _safe_remove(dump_path)
        return

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _gzip_file, dump_path, gz_path)
        await _send_document(bot, channel_id, gz_path, f"🗄 DB backup — {day}")
        logger.info("DB backup kanalga yuborildi: %s", day)
    finally:
        _safe_remove(dump_path)
        _safe_remove(gz_path)


async def _do_daily(bot: Bot, channel_id: int) -> None:
    """Bir martalik kunlik backup: log + DB."""
    # Log yozib rotatsiyani "turtib" yuboramiz (agar hali sodir bo'lmagan bo'lsa),
    # keyin listener thread diskka flush qilishiga ozgina kutamiz.
    logger.info("Kunlik backup boshlandi")
    await asyncio.sleep(3)

    day = (datetime.now() - timedelta(days=1)).strftime("%d_%m_%Y")
    log_dir = os.path.dirname(settings.log_file) or "."
    tmp_dir = os.path.join(log_dir, "_backup_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        await _backup_logs(bot, channel_id, day, tmp_dir)
    except Exception:
        logger.exception("Log backup xatolik")

    try:
        await _backup_db(bot, channel_id, day, tmp_dir)
    except Exception:
        logger.exception("DB backup xatolik")


async def _loop(bot: Bot, channel_id: int, hour: int, minute: int) -> None:
    logger.info(
        "Backup scheduler ishga tushdi — har kuni %02d:%02d, kanal=%s",
        hour, minute, channel_id,
    )
    while True:
        try:
            await asyncio.sleep(_seconds_until(hour, minute))
            await _do_daily(bot, channel_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler siklida kutilmagan xatolik")
            await asyncio.sleep(60)  # tinim olib, davom etamiz


def start_scheduler(bot: Bot) -> None:
    """Kunlik backup taskini ishga tushiradi (kanal sozlangan bo'lsa)."""
    global _task
    channel_id = settings.backup_channel_id
    if not channel_id:
        logger.warning("BACKUP_CHANNEL_ID/CHANNEL_ID sozlanmagan — kunlik backup O'CHIRILGAN")
        return
    if _task is not None:
        return
    hour, minute = _parse_hhmm(settings.backup_time)
    _task = asyncio.create_task(_loop(bot, channel_id, hour, minute))


async def stop_scheduler() -> None:
    """Kunlik backup taskini to'xtatadi."""
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
