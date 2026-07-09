"""
JSON formatda logging — ASINXRON (queue orqali) fayl (KUNLIK rotation) + konsol.

NEGA QUEUE:
- Ilgari har log chaqiruvi diskka SINXRON yozardi — event-loop ichida.
  Yuqori yukda bu loopni bloklaydi (bot sekinlashadi).
- Endi handler faqat log yozuvini navbatga (queue) qo'yadi (tez, bloklamaydi).
  Haqiqiy diskka yozishni ALOHIDA thread (QueueListener) bajaradi.

Har bir log yozuvida: vaqt (ISO), level, message, va qo'shimcha maydonlar.
"""

import json
import logging
import os
import queue
import sys
from datetime import datetime, timezone
from logging.handlers import QueueHandler, QueueListener
from typing import Optional


class JSONFormatter(logging.Formatter):
    """Log yozuvlarini JSON formatda chiqaradi."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Standard LogRecord attributlari, ularni e'tiborsiz qoldiramiz
        standard_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "module",
            "msecs", "message", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "thread", "threadName",
            "taskName",
        }

        # Barcha extra (qo'shimcha) maydonlarni dinamik qo'shish
        for key, value in record.__dict__.items():
            if key not in standard_keys and value is not None:
                log_data[key] = value

        if record.exc_info and record.exc_info[1]:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class _PassthroughQueueHandler(QueueHandler):
    """
    Oddiy QueueHandler yozuvni oldindan formatlaydi va exc_info ni tozalaydi —
    natijada JSONFormatter dagi 'exception' maydoni yo'qoladi.

    Bu variant yozuvni O'ZGARTIRMASDAN navbatga qo'yadi. Formatlashni
    (jumladan exception traceback ni) listener thread dagi JSONFormatter bajaradi.
    (Biz thread queue ishlatamiz — pickling shart emas, record ni to'g'ridan uzatsa bo'ladi.)
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record


# Listener obyekti (alohida thread) — global saqlanadi, shutdown da to'xtatiladi
_listener: Optional[QueueListener] = None


class DailyDatedFileHandler(logging.FileHandler):
    """
    Har kuni ALOHIDA sana nomli faylga yozadi:  log_KUN_OY_YIL.log
    (masalan: logs/log_09_07_2026.log).

    - Joriy kun uchun fayl DARROV shu nom bilan yaratiladi ("bot.log" yo'q).
    - Yarim tunda (mahalliy vaqt) avtomatik yangi kun fayliga o'tadi —
      keyingi log yozuvi kelganda sana o'zgargani tekshiriladi.
    - Eski fayllar O'CHIRILMAYDI (serverda qoladi).

    Bu handler QueueListener thread ichida (bitta thread) ishlaydi —
    shuning uchun qo'shimcha lock kerak emas.
    """

    def __init__(self, log_dir: str, encoding: str = "utf-8") -> None:
        self.log_dir = log_dir or "."
        os.makedirs(self.log_dir, exist_ok=True)
        self._current_day = self._today()
        super().__init__(self._path_for(self._current_day), encoding=encoding, delay=False)

    @staticmethod
    def _today() -> str:
        # Mahalliy vaqt bo'yicha "KUN_OY_YIL"
        return datetime.now().strftime("%d_%m_%Y")

    def _path_for(self, day: str) -> str:
        return os.path.join(self.log_dir, f"log_{day}.log")

    def emit(self, record: logging.LogRecord) -> None:
        day = self._today()
        if day != self._current_day:
            # Kun almashdi — eski faylni yopib, yangi sana fayliga o'tamiz
            self._current_day = day
            self.baseFilename = os.path.abspath(self._path_for(day))
            if self.stream:
                self.stream.close()
                self.stream = None
            self.stream = self._open()
        super().emit(record)


def setup_logger(
    name: str = "bot",
    level: str = "INFO",
    log_file: str = "logs/bot.log",
) -> logging.Logger:
    """Logger yaratadi — JSON formatda, ASINXRON konsol + faylga yozadi."""
    global _listener

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Takroriy handler qo'shmaslik
    if logger.handlers:
        return logger

    json_formatter = JSONFormatter()

    # --- Haqiqiy handlerlar (bularni listener thread ishlatadi) ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(json_formatter)

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Har kuni ALOHIDA sana nomli faylga yozadi: logs/log_KUN_OY_YIL.log
    # Yarim tunda avtomatik yangi kun fayliga o'tadi. Eski fayllar serverda qoladi.
    file_handler = DailyDatedFileHandler(log_dir=log_dir or ".")
    file_handler.setFormatter(json_formatter)

    # --- Navbat + bloklamaydigan handler (event-loop shu handler ni ishlatadi) ---
    # Cheksiz navbat (-1): log yo'qotmaymiz. Yozuvlar juda yengil (kichik obyekt).
    log_queue: "queue.Queue" = queue.Queue(-1)
    queue_handler = _PassthroughQueueHandler(log_queue)
    logger.addHandler(queue_handler)

    # Listener alohida (daemon) thread da haqiqiy diskka/konsolga yozadi
    _listener = QueueListener(
        log_queue,
        console_handler,
        file_handler,
        respect_handler_level=True,
    )
    _listener.start()

    return logger


def stop_logging() -> None:
    """
    Listener thread ni to'xtatadi (navbatdagi loglarni flush qiladi).
    Bot to'xtayotganda chaqiriladi.
    """
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
