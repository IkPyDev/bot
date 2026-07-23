# Loyiha qoidalari

Bu — aiogram asosidagi Telegram business bot. Quyidagi qoidalar majburiy.

## 1. Telegram Premium haqida HECH QACHON yozilmasin

Botni ulash uchun **Telegram Premium SHART EMAS** — bot oddiy (Premium'siz)
foydalanuvchilar uchun ham to'liq ishlaydi. Business chatbot ulash barcha
akkauntlarga ochiq.

**Shuning uchun:**
- Foydalanuvchiga ko'rinadigan hech qanday matnga "Premium kerak",
  "Premium bo'lishi shart", "faqat Premium uchun" kabi ogohlantirish
  QO'SHILMASIN (caption, xabar, tugma, xatolik matni — hech qayerga).
- Kodga yoki izohga ham "Premium talab qilinadi" deb yozilmasin.
- Bunday qator topilsa — o'chirilsin, so'ramasdan.

**Sabab:** noto'g'ri ogohlantirish oddiy foydalanuvchini qo'rqitib,
botdan voz kechishiga sabab bo'ladi.

## 2. Foydalanuvchiga ko'rinadigan matnlar

- Til: **o'zbekcha**, oddiy va tushunarli. Texnik jargon ishlatilmasin —
  matnni birinchi marta bot ko'rgan odam ham tushunsin.
- Qo'llanmalar **qadamma-qadam** (1️⃣ 2️⃣ 3️⃣ ...) yozilsin, emoji bilan.
- Faqat Telegram qo'llab-quvvatlaydigan HTML teglaridan foydalaning:
  `<b>`, `<i>`, `<code>`, `<blockquote>`. Bot `parse_mode="HTML"` bilan ishlaydi.
- **Caption chegarasi — 1024 belgi** (teglar sanalmaydi, faqat ko'rinadigan matn).
  Oshib ketsa Telegram `MEDIA_CAPTION_TOO_LONG` qaytaradi va bot media o'rniga
  faqat matn yuborishga tushib qoladi. Matn uzaytirilganda uzunlik tekshirilsin.

## 3. Media (rasm/video) bilan ishlash

- Media "database" kanalida turadi, `copy_message` bilan olinadi —
  **file_id kodga yozib qo'yilmaydi** (file_id eskiradi, copy_message eskirmaydi).
- Kanal/xabar ID lari **faqat `.env`** orqali sozlanadi, kodga qattiq yozilmasin.
  Yangi ID qo'shilsa — `app/config.py`, `.env` va `.env.example` uchalasi yangilansin.
- Media yuborish har doim `try/except` ichida bo'lsin: kanal topilmasa yoki bot
  a'zo bo'lmasa — bot yiqilmasin, matn bilan yuborsin va logga `warning` yozsin.
