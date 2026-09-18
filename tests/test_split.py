"""Uzun matnni bo'lish tekshiruvi. Ishga tushirish: python tests/test_split.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram.types import MessageEntity  # noqa: E402

from app.handlers.message import _concat_text, _split_text, _u16  # noqa: E402

text = ("salom 😀 dunyo\n" * 600).strip()
ents = [MessageEntity(type="bold", offset=0, length=_u16(text))]
parts = _split_text(text, ents, 4000, 4056)

assert len(parts) == 3, len(parts)
assert "".join(p[0] for p in parts) == text  # hech narsa yo'qolmadi
for chunk, chunk_ents in parts:
    assert _u16(chunk) <= 4056
    assert chunk_ents[0].offset == 0 and chunk_ents[0].length == _u16(chunk)

t, e = _concat_text(("😀a", [MessageEntity(type="bold", offset=0, length=3)]), ("b", [MessageEntity(type="italic", offset=0, length=1)]))
assert t == "😀ab" and e[1].offset == 3  # emoji = 2 UTF-16 birlik

print("OK")
