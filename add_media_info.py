import re

with open("app/handlers/message.py", "r") as f:
    content = f.read()

# Add _extract_media_info helper
helper = """
def _extract_media_info(msg: Message, ctype: str) -> str:
    lines = []
    if getattr(msg, "has_protected_content", False):
        lines.append("🔒 Himoyalangan (Protected): HA")
    if ctype == "photo" and msg.photo:
        lines.append(f"📄 File ID: {msg.photo[-1].file_id}")
        lines.append(f"📦 Size: {getattr(msg.photo[-1], 'file_size', 0)} bayt")
    elif ctype == "video" and msg.video:
        lines.append(f"📄 File ID: {msg.video.file_id}")
        lines.append(f"⏳ Davomiylik: {getattr(msg.video, 'duration', 0)}s")
        lines.append(f"📦 Size: {getattr(msg.video, 'file_size', 0)} bayt")
    elif ctype == "voice" and msg.voice:
        lines.append(f"📄 File ID: {msg.voice.file_id}")
        lines.append(f"⏳ Davomiylik: {getattr(msg.voice, 'duration', 0)}s")
    elif ctype == "video_note" and msg.video_note:
        lines.append(f"📄 File ID: {msg.video_note.file_id}")
        lines.append(f"⏳ Davomiylik: {getattr(msg.video_note, 'duration', 0)}s")
    elif ctype == "audio" and msg.audio:
        lines.append(f"📄 File ID: {msg.audio.file_id}")
        lines.append(f"⏳ Davomiylik: {getattr(msg.audio, 'duration', 0)}s")
    elif ctype == "document" and msg.document:
        lines.append(f"📄 File ID: {msg.document.file_id}")
        if msg.document.file_name:
            lines.append(f"📁 Nomi: {msg.document.file_name}")
    elif ctype == "sticker" and msg.sticker:
        lines.append(f"📄 File ID: {msg.sticker.file_id}")
        if msg.sticker.emoji:
            lines.append(f"😀 Emoji: {msg.sticker.emoji}")
        if getattr(msg.sticker, "set_name", None):
            lines.append(f"📚 Set: {msg.sticker.set_name}")
    return "\\n".join(lines)
"""

if "_extract_media_info" not in content:
    content = content.replace("def _build_channel_header(", helper + "\n\ndef _build_channel_header(")

with open("app/handlers/message.py", "w") as f:
    f.write(content)
