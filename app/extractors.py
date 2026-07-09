"""
Xabardan content_type va turga xos maydonlarni ajratish.

NIMA QILADI:
- Xabarning turini aniqlaydi: text, photo, voice, video, document, sticker, ...
- Turga qarab kerakli maydonlarni ajratadi (file_id, duration, mime_type, ...)
- Matn yoki caption ni toza holatda qaytaradi (AI tahlili uchun muhim)
- Xabar yo'nalishini aniqlaydi: incoming (mijozdan) yoki outgoing (xodimdan)

QANDAY ISHLAYDI:
- detect_content_type() — aiogram Message obyektidan qaysi maydon borligini tekshiradi
- extract_text_or_caption() — text yoki caption ni qaytaradi
- extract_media_fields() — media turlariga xos maydonlarni dict qilib qaytaradi
- determine_direction() — from_user_id ni connection owner bilan solishtiradi

12 TA TUR (content_type):
1.  text       — oddiy matn
2.  photo      — rasm (eng katta o'lcham olinadi)
3.  video      — video
4.  voice      — ovozli xabar
5.  video_note — dumaloq video (telegram circles)
6.  audio      — audio fayl / musiqa
7.  document   — hujjat / fayl
8.  sticker    — stiker
9.  contact    — kontakt (telefon raqami)
10. location   — joylashuv (koordinatalar)
11. venue      — joy (nomi + manzili + koordinatalar)
12. poll       — so'rovnoma
13. unknown    — noma'lum (logga WARNING chiqadi)
"""

import logging
from typing import Any, Optional

from aiogram.types import Message

logger = logging.getLogger("bot.extractors")


def detect_content_type(message: Message) -> str:
    """
    Xabarning content_type'ini aniqlaydi.

    aiogram Message obyektida qaysi maydon None bo'lmasa —
    shu tur deb hisoblanadi. Tartib muhim: photo dan oldin
    text tekshiriladi, chunki ba'zi xabarlarda ikkalasi bo'lishi mumkin.
    """
    if message.text is not None:       # oddiy matnli xabar
        return "text"
    if message.photo:                   # rasm (list, har xil o'lchamda)
        return "photo"
    if message.video:                   # video fayl
        return "video"
    if message.voice:                   # ovozli xabar (ogg format)
        return "voice"
    if message.video_note:              # dumaloq video xabar
        return "video_note"
    if message.audio:                   # audio/musiqa fayl
        return "audio"
    if message.document:                # hujjat / har qanday fayl
        return "document"
    if message.sticker:                 # stiker
        return "sticker"
    if message.contact:                 # kontakt (telefon raqami)
        return "contact"
    if message.location:                # joylashuv (lat/lon)
        return "location"
    if message.venue:                   # joy (nomi + manzil + lat/lon)
        return "venue"
    if message.poll:                    # so'rovnoma
        return "poll"

    # Noma'lum tur — WARNING logga chiqadi, lekin raw_json ga baribir saqlanadi
    logger.warning("Unknown content_type for message_id=%d", message.message_id)
    return "unknown"


def extract_text_or_caption(message: Message, content_type: str) -> Optional[str]:
    """
    Toza matn ajratadi — AI tahlili uchun eng muhim maydon.

    - text xabar → message.text qaytariladi
    - media xabar → message.caption qaytariladi (agar bo'lsa)
    - matn/caption yo'q → None

    AI keyinchalik aynan shu maydonni o'qiydi.
    """
    if content_type == "text":
        return message.text
    # photo, video, document, ... — ularning tagida caption bo'lishi mumkin
    return getattr(message, "caption", None)


def extract_media_fields(
    message: Message, content_type: str
) -> dict[str, Any]:
    """
    Turga xos maydonlarni dict qilib qaytaradi.

    Bazaga yoziladi:
    - media_file_id   — Telegram file_id (keyinchalik fayl yuklab olish uchun)
    - media_file_name — fayl nomi (document, audio uchun)
    - media_mime      — MIME turi (image/jpeg, audio/ogg, video/mp4, ...)
    - media_duration  — davomiyligi sekundlarda (video, voice, audio uchun)

    Qolgan turga xos ma'lumotlar (masalan sticker emoji, contact phone)
    raw_json da to'liq saqlanadi — bu yerda ajratilmaydi.
    """
    result: dict[str, Any] = {
        "media_file_id": None,
        "media_file_name": None,
        "media_mime": None,
        "media_duration": None,
    }

    # text xabarda media yo'q
    if content_type == "text":
        return result

    # PHOTO — bir nechta o'lchamda keladi, eng kattasini olamiz
    if content_type == "photo" and message.photo:
        largest = message.photo[-1]  # oxirgisi = eng katta o'lcham
        result["media_file_id"] = largest.file_id
        return result

    # VIDEO — file_id, MIME turi, davomiyligi
    if content_type == "video" and message.video:
        result["media_file_id"] = message.video.file_id
        result["media_mime"] = message.video.mime_type
        result["media_duration"] = message.video.duration
        return result

    # VOICE — ovozli xabar (ogg format, sekundlarda)
    if content_type == "voice" and message.voice:
        result["media_file_id"] = message.voice.file_id
        result["media_mime"] = message.voice.mime_type
        result["media_duration"] = message.voice.duration
        return result

    # VIDEO_NOTE — dumaloq video (duration + length)
    if content_type == "video_note" and message.video_note:
        result["media_file_id"] = message.video_note.file_id
        result["media_duration"] = message.video_note.duration
        return result

    # AUDIO — musiqa / audio fayl (title, performer, duration)
    if content_type == "audio" and message.audio:
        result["media_file_id"] = message.audio.file_id
        result["media_mime"] = getattr(message.audio, "mime_type", None)
        result["media_duration"] = message.audio.duration
        result["media_file_name"] = message.audio.title or message.audio.file_name
        return result

    # DOCUMENT — har qanday fayl (PDF, Word, ZIP, ...)
    if content_type == "document" and message.document:
        result["media_file_id"] = message.document.file_id
        result["media_file_name"] = message.document.file_name
        result["media_mime"] = message.document.mime_type
        return result

    # STICKER — file_id bor, lekin mime/duration kerak emas
    if content_type == "sticker" and message.sticker:
        result["media_file_id"] = message.sticker.file_id
        return result

    # CONTACT, LOCATION, VENUE, POLL — media_file_id kerak emas
    # Ularning barcha ma'lumotlari raw_json da to'liq saqlanadi
    return result


def determine_direction(from_user_id: Optional[int], owner_user_id: Optional[int]) -> str:
    """
    Xabar yo'nalishini aniqlaydi — AI tahlili uchun juda muhim.

    Qoida:
    - from_user_id == owner_user_id → "outgoing" (XODIM yozdi mijozga)
    - from_user_id != owner_user_id → "incoming" (MIJOZ yozdi xodimga)

    owner_user_id — bu botni ulagan xodimning Telegram user ID si.
    U business_connection eventidan olinadi va cache'da saqlanadi.
    """
    if from_user_id is not None and owner_user_id is not None:
        if from_user_id == owner_user_id:
            return "outgoing"  # xodim → mijoz
    return "incoming"  # mijoz → xodim
