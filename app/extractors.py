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

import json
import logging
from typing import Any, Optional

from aiogram.types import Message, MessageEntity

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

    # Tizim / maxsus xabarlar (pin, avto-o'chirish, story, sovg'a, maqola, ...).
    # Tur nomi — Telegram maydon nomining o'zi. Yangi tur chiqsa ham shu yerda ushlanadi.
    special = _special_key(message)
    if special:
        return special

    # Noma'lum tur — WARNING logga chiqadi, lekin raw_json ga baribir saqlanadi
    logger.warning("Unknown content_type for message_id=%d", message.message_id)
    return "unknown"


# ============================================================
# MAXSUS / TIZIM XABARLARI — o'qiladigan matnga aylantirish
# ============================================================

# Xabar "turi" emas, balki qo'shimcha ma'lumot bo'lgan maydonlar
_META_KEYS = {
    "message_id", "date", "chat", "from_user", "from", "business_connection_id",
    "sender_chat", "sender_business_bot", "sender_boost_count", "sender_tag",
    "forward_origin", "forward_date", "forward_from", "forward_from_chat",
    "forward_from_message_id", "forward_signature", "forward_sender_name",
    "is_automatic_forward", "is_topic_message", "message_thread_id", "is_from_offline",
    "reply_to_message", "reply_to_story", "reply_to_checklist_task_id", "external_reply",
    "quote", "via_bot", "edit_date", "has_protected_content", "media_group_id",
    "author_signature", "paid_star_count", "entities", "caption", "caption_entities",
    "show_caption_above_media", "has_media_spoiler", "link_preview_options",
    "effect_id", "reply_markup", "text", "is_paid_post", "direct_messages_topic",
    "suggested_post_info",
}


def _special_key(message: Message) -> Optional[str]:
    """Oddiy turlarga kirmagan xabarning asosiy maydon nomi (masalan 'story')."""
    raw = message.model_dump(exclude_none=True, by_alias=True)
    for key in raw:
        if key not in _META_KEYS and raw[key] not in (False, [], {}, ""):
            return key
    return None


def _human_seconds(sec: int) -> str:
    days = sec // 86400
    if days >= 365:
        return f"{days // 365} yil"
    if days >= 30:
        return f"{days // 30} oy"
    if days >= 7:
        return f"{days // 7} hafta"
    if days:
        return f"{days} kun"
    if sec >= 3600:
        return f"{sec // 3600} soat"
    return f"{sec // 60} daqiqa"


def _chat_label(chat: dict) -> str:
    name = chat.get("title") or " ".join(
        p for p in [chat.get("first_name"), chat.get("last_name")] if p
    )
    parts = [name] if name else []
    if chat.get("username"):
        parts.append(f"@{chat['username']}")
    parts.append(f"[ID: {chat.get('id')}]")
    return " ".join(parts)


# rich_message ichidagi inline turlar -> Telegram entity turi
_RICH_ENTITY = {
    "bold": "bold", "italic": "italic", "underline": "underline",
    "strikethrough": "strikethrough", "spoiler": "spoiler", "code": "code",
}


class _TextBuilder:
    """Matn + entity'larni (UTF-16 offset bilan) birga yig'adi."""

    def __init__(self) -> None:
        self.text = ""
        self.entities: list[MessageEntity] = []

    def pos(self) -> int:
        return len(self.text.encode("utf-16-le")) // 2

    def add(self, s: str, etype: Optional[str] = None, **kw: Any) -> None:
        start = self.pos()
        self.text += s
        self.mark(start, etype, **kw)

    def mark(self, start: int, etype: Optional[str], **kw: Any) -> None:
        length = self.pos() - start
        if etype and length > 0:
            self.entities.append(MessageEntity(type=etype, offset=start, length=length, **kw))

    def result(self) -> tuple[str, list[MessageEntity]]:
        # Faqat oxiridagi bo'shliq olinadi (boshidan olinsa offsetlar suriladi)
        text = self.text.rstrip()
        total = len(text.encode("utf-16-le")) // 2
        ents = []
        for e in self.entities:
            length = min(e.length, total - e.offset)
            if length > 0:
                ents.append(e.model_copy(update={"length": length}))
        # Tashqi entity oldin kelsin (bir xil offsetda — uzunrog'i birinchi)
        ents.sort(key=lambda e: (e.offset, -e.length))
        return text, ents


def _rich_inline(b: _TextBuilder, node: Any) -> None:
    """rich_message inline matni: str | list | {"type": ..., "text": ...}."""
    if isinstance(node, str):
        b.add(node)
    elif isinstance(node, list):
        for item in node:
            _rich_inline(b, item)
    elif isinstance(node, dict):
        ntype = node.get("type")
        if ntype == "custom_emoji":
            b.add(node.get("alternative_text") or "")
            return
        start = b.pos()
        _rich_inline(b, node.get("text", ""))
        if node.get("url"):
            b.mark(start, "text_link", url=node["url"])
        elif ntype in _RICH_ENTITY:
            b.mark(start, _RICH_ENTITY[ntype])


def _rich_block(b: _TextBuilder, block: dict, photos: list[str]) -> None:
    """rich_message bloki (heading, paragraph, photo, table, pre, blockquote, ...)."""
    btype = block.get("type")
    start = b.pos()
    if btype == "heading":
        _rich_inline(b, block.get("text", ""))
        b.mark(start, "bold")
    elif btype == "pre":
        _rich_inline(b, block.get("text", ""))
        b.mark(start, "pre", language=block.get("language"))
    elif btype == "divider":
        b.add("———")
    elif btype == "photo":
        photos.append(block["photo"][-1]["file_id"])
        b.add(f"🖼 [rasm {len(photos)}]")
        if block.get("caption"):
            b.add(" ")
            _rich_inline(b, block["caption"])
    elif btype == "table":
        for row in block.get("cells", []):
            if not any(cell.get("text") for cell in row):
                continue  # bo'sh (sarlavha) qator
            for i, cell in enumerate(row):
                if i:
                    b.add(" | ")
                _rich_inline(b, cell.get("text", ""))
            b.add("\n")
    elif "blocks" in block:  # blockquote va ichma-ich bloklar
        for sub in block["blocks"]:
            _rich_block(b, sub, photos)
        if btype == "blockquote":
            b.mark(start, "blockquote")
    elif "items" in block:  # ro'yxat
        for item in block["items"]:
            b.add("• ")
            if isinstance(item, dict) and "type" in item and "text" not in item:
                _rich_block(b, item, photos)
            else:
                _rich_inline(b, item.get("text", item) if isinstance(item, dict) else item)
            b.add("\n")
    else:
        _rich_inline(b, block.get("text", ""))
    b.add("\n\n")


def special_content(
    message: Message, content_type: str
) -> Optional[tuple[str, list[MessageEntity], list[str]]]:
    """
    Oddiy matn/media bo'lmagan xabarni o'qiladigan matnga aylantiradi.

    Qaytaradi: (matn, entity'lar, rasm file_id'lari) yoki None.
    Telegram bergan ma'lumot to'liq chiqariladi; noma'lum tur bo'lsa ham
    maydonlari yoziladi — "[unknown]" bo'lib qolmaydi.
    """
    if content_type in ("text", "photo", "video", "voice", "video_note", "audio",
                        "document", "sticker", "contact", "location", "venue"):
        return None
    raw = message.model_dump(mode="json", exclude_none=True, by_alias=True)
    b = _TextBuilder()
    photos: list[str] = []

    if content_type == "poll":
        p = raw["poll"]
        b.add("📊 So'rovnoma: ")
        b.add(p.get("question", ""), "bold")
        for i, opt in enumerate(p.get("options", []), 1):
            b.add(f"\n{i}. {opt.get('text', '')} — {opt.get('voter_count', 0)} ovoz")
        flags = [
            "anonim" if p.get("is_anonymous") else "ochiq",
            "bir nechta javob" if p.get("allows_multiple_answers") else "bitta javob",
        ]
        if p.get("type") == "quiz":
            flags.append("viktorina")
        if p.get("is_closed"):
            flags.append("yopilgan")
        b.add(f"\n({', '.join(flags)}; jami {p.get('total_voter_count', 0)} ovoz)")

    elif content_type == "rich_message":
        for block in raw["rich_message"].get("blocks", []):
            _rich_block(b, block, photos)

    elif content_type == "pinned_message":
        pm = raw["pinned_message"]
        b.add("📌 Xabar qadaldi (pin)\n")
        body = pm.get("text") or pm.get("caption")
        if body:
            b.add(f"✍️ Qadalgan xabar: {body}\n")
        else:
            kind = next((k for k in pm if k not in _META_KEYS), "xabar")
            b.add(f"✍️ Qadalgan xabar turi: {kind}\n")
        b.add(f"🆔 Qadalgan xabar ID: {pm.get('message_id')}")

    elif content_type == "message_auto_delete_timer_changed":
        sec = raw[content_type].get("message_auto_delete_time", 0)
        if sec:
            b.add(f"⏲ Avto-o'chirish yoqildi: xabarlar {_human_seconds(sec)}dan keyin o'chadi")
        else:
            b.add("⏲ Avto-o'chirish o'chirildi: xabarlar endi o'zi o'chmaydi")

    elif content_type == "story":
        st = raw["story"]
        chat = st.get("chat", {})
        b.add("📖 Story ulashildi\n")
        b.add(f"👤 Kimning storysi: {_chat_label(chat)}\n")
        b.add(f"🆔 Story ID: {st.get('id')}")
        if chat.get("username"):
            b.add(f"\n🔗 https://t.me/{chat['username']}/s/{st.get('id')}")

    elif content_type in ("gift", "unique_gift"):
        g = raw[content_type]
        inner = g.get("gift", {})
        b.add("🎁 Sovg'a yuborildi\n")
        emoji = (inner.get("sticker") or {}).get("emoji")
        if emoji:
            b.add(f"😀 Sovg'a: {emoji}\n")
        for key, label in (("name", "📛 Nomi"), ("base_name", "📛 Nomi"), ("number", "#️⃣ Raqami")):
            if inner.get(key):
                b.add(f"{label}: {inner[key]}\n")
        if inner.get("star_count"):
            b.add(f"⭐ Narxi: {inner['star_count']} yulduz\n")
        if g.get("convert_star_count"):
            b.add(f"💱 Yulduzga almashtirsa: {g['convert_star_count']} ⭐\n")
        if g.get("text"):
            b.add(f"✍️ Sovg'a matni: {g['text']}\n")
        if g.get("is_private"):
            b.add("🔒 Yuboruvchi yashirin\n")

    elif content_type == "poll_option_added":
        po = raw[content_type]
        b.add("📊 So'rovnomaga yangi variant qo'shildi: ")
        b.add(po.get("option_text", ""), "bold")
        pmsg = po.get("poll_message") or {}
        if pmsg.get("message_id"):
            b.add(f"\n🆔 So'rovnoma xabari ID: {pmsg['message_id']}")

    elif content_type == "dice":
        d = raw["dice"]
        b.add(f"🎲 {d.get('emoji', '🎲')} tashlandi — natija: {d.get('value')}")

    else:
        # Boshqa har qanday tur (yangi Telegram turlari ham) — maydonlari bilan
        data = raw.get(content_type)
        b.add(f"ℹ️ Xabar turi: {content_type}\n")
        if data is not None:
            dump = json.dumps(data, ensure_ascii=False, indent=1)
            b.add(dump[:3500] + ("…" if len(dump) > 3500 else ""), "pre")

    text, entities = b.result()
    return text, entities, photos


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
    caption = getattr(message, "caption", None)
    if caption:
        return caption
    # So'rovnoma, story, sovg'a, pin, maqola, ... — o'qiladigan tavsif
    try:
        special = special_content(message, content_type)
    except Exception:
        logger.warning("special_content xato (msg_id=%s)", message.message_id, exc_info=True)
        return None
    return special[0] if special else None


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
