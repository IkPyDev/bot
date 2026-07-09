# Telegram Business — Xabar Yig'uvchi Bot (Texnik Topshiriq)

> Bu hujjat AI'ga (yoki dasturchiga) beriladigan topshiriq. Bu yerda **nima qurilishi**
> aniq yozilgan. Kodni AI yozadi. Texnik nomlar (jadval, maydon, handler) ingliz tilida
> qoldirilgan — ular kodda shunday bo'ladi.

---

## 1. Maqsad va doira (Scope)

Bu bot **faqat xabar yig'adi**. U:

- ✅ Cheksiz akkauntga ulanadi (har bir Telegram Business connection).
- ✅ Ruxsat berilgan chatlardagi har bir xabarni qabul qiladi.
- ✅ Har bir xabarning **turini (content_type)** aniqlaydi va turga mos ma'lumotni ajratadi.
- ✅ Har bir xabarni **to'liq logga** chiqaradi.
- ✅ Bazaga (PostgreSQL) saqlaydi.

Bu bot **QILMAYDIGAN** ishlar (muhim!):

- ❌ Hech kimga javob yozmaydi (no reply, no auto-reply).
- ❌ AI tahlil qilmaydi. Tahlil — **alohida tizim**, alohida serverda, bazadan o'qib ishlaydi.
- ❌ Og'ir hisob-kitob qilmaydi. Vazifasi — tez qabul qilib, tez saqlash.

Sabab: 2 ta og'ir ishni (yig'ish + AI) bitta serverga qo'ymaslik. Bu bot yengil ishlaydi,
AI worker bazaga kuniga 1 marta kirib, o'z ishini qiladi.

---

## 2. Texnologiyalar

| Komponent | Tanlov |
|-----------|--------|
| Til | Python 3.11+ |
| Bot framework | **aiogram 3.x** (async) |
| Baza | **PostgreSQL** |
| Baza drayveri | `asyncpg` (yoki SQLAlchemy 2.x async) |
| Log | standart `logging`, JSON formatda, fayl + konsol, rotation bilan |
| Update olish | boshlanishiga **polling**, keyin **webhook** (domен + HTTPS bo'lsa) |

---

## 3. Qabul qilinadigan Update turlari

aiogram 3'da bular `Router` observerlari orqali ushlanadi:

```
@router.business_connection()       # xodim botni uladi / o'chirdi / o'zgartirdi
@router.business_message()          # yangi xabar (kelgan yoki yuborilgan)
@router.edited_business_message()   # tahrirlangan xabar
@router.deleted_business_messages() # o'chirilgan xabar(lar)
```

To'rttasi ham qo'llanishi shart.

---

## 4. `business_connection` ishlovi

Keladigan obyekt — `BusinessConnection`, maydonlari:

- `id` — connection identifikatori (string). **Har bir xodimni shu ajratadi.**
- `user` — botni ulagan xodim (User: id, first_name, username, ...).
- `user_chat_id` — xodim bilan shaxsiy chat id.
- `date` — ulangan vaqt.
- `can_reply` — bot javob yoza oladimi (bizda kerak emas, lekin saqlab qo'yamiz).
  > Eslatma: yangi Bot API versiyalarida bu `rights` (BusinessBotRights) bo'lishi mumkin.
  > AI joriy aiogram versiyasiga qarab moslasin.
- `is_enabled` — ulanish faolmi.

Mantiq:

1. Yangi ulanish kelsa → `connections` jadvaliga **insert yoki update** (upsert by `id`).
2. `is_enabled = false` kelsa → o'sha connection "o'chirilgan" deb belgilansin (lekin o'chirilmasin, tarix qolsin).
3. Hammasi **to'liq logga** chiqsin.

> ⚠️ **Muhim cheklov:** Telegram bu update'da "xodim qaysi chatlarga ruxsat berdi"
> degan ro'yxatni **bermaydi**. Ruxsat etilgan chatlar xodim tomonida (Settings) sozlanadi.
> Bot esa o'sha chatlardan **xabar kelgani sayin** ularni "kashf qiladi" (4-bandga qarang).

---

## 5. `business_message` ishlovi — ENG MUHIM QISM

Har bir xabar uchun: **umumiy maydonlar** + **turga xos maydonlar** ajratiladi.

### 5.1. Har bir xabar uchun umumiy maydonlar

- `business_connection_id` — qaysi xodimning chati (FK → connections.id).
- `chat_id`, `chat_type`, `chat_title`/`chat_username` — mijoz chati.
- `from_user_id`, `from_user_first_name`, `from_user_username`.
- `message_id`.
- `date` (Telegram vaqti).
- `direction` — **incoming** (mijozdan) yoki **outgoing** (xodimdan).
  - Aniqlash qoidasi: agar `from_user.id == connection.user.id` → **outgoing** (xodim yozdi),
    aks holda → **incoming** (mijoz yozdi).
- `content_type` — quyidagi turlardan biri.
- `raw_json` — **butun update'ning JSON nusxasi** (JSONB). Kelajakda yangi maydon kerak
  bo'lsa, qayta ishlov berish uchun oltin zaxira. Doim saqlansin.

### 5.2. Turga xos ajratish (content_type → saqlanadigan maydonlar)

| content_type | Ajratiladigan maydonlar |
|--------------|-------------------------|
| `text` | `text` (to'liq matn) |
| `photo` | eng katta o'lchamning `file_id`, `file_unique_id`, `width`, `height`, `caption` |
| `video` | `file_id`, `duration`, `mime_type`, `file_size`, `caption` |
| `voice` | `file_id`, `duration`, `mime_type`, `file_size` |
| `video_note` | `file_id`, `duration`, `length` |
| `audio` | `file_id`, `title`, `performer`, `duration` |
| `document` | `file_id`, `file_name`, `mime_type`, `file_size`, `caption` |
| `sticker` | `file_id`, `emoji`, `set_name`, `is_animated`, `is_video` |
| `contact` | `phone_number`, `first_name`, `last_name`, `user_id` |
| `location` | `latitude`, `longitude` |
| `venue` | `title`, `address`, `latitude`, `longitude` |
| `poll` | `question`, variantlar |
| boshqa/noma'lum | turini logga WARNING qilib, `raw_json`ni baribir saqla |

### 5.3. AI tahlili uchun nima muhim (bu bot uchun yo'l-yo'riq)

AI keyinchalik bazadan o'qiganda, asosan **matnli ma'no** kerak bo'ladi:

- `text` va `caption` — eng muhim. Bularni **alohida, toza** maydonda saqla.
- Media (photo/voice/...) bo'lsa — kamida `content_type` + `caption` saqlanadi,
  shunda AI "bu yerda rasm/ovozli xabar yuborilgan" deb tushunadi.
- `direction` — AI uchun juda muhim (mijoz nima dedi, xodim nima dedi).
- `raw_json` — hech narsa yo'qolmasligi uchun.

Shu sababli baza shunday tuzilsin: **matn ajratib olinadi**, lekin xom JSON ham qoladi.

---

## 6. Ma'lumotlar bazasi sxemasi (PostgreSQL)

```sql
-- Botni ulagan xodimlar
CREATE TABLE connections (
    id              TEXT PRIMARY KEY,        -- business_connection_id
    user_id         BIGINT NOT NULL,         -- xodimning Telegram user id
    user_chat_id    BIGINT,
    username        TEXT,
    first_name      TEXT,
    can_reply       BOOLEAN,
    is_enabled      BOOLEAN DEFAULT TRUE,
    connected_at    TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Kashf qilingan chatlar (ixtiyoriy, lekin foydali)
CREATE TABLE chats (
    connection_id   TEXT REFERENCES connections(id),
    chat_id         BIGINT,
    chat_type       TEXT,
    title           TEXT,
    username        TEXT,
    first_seen      TIMESTAMPTZ DEFAULT now(),
    last_message_at TIMESTAMPTZ,
    message_count   INTEGER DEFAULT 0,
    PRIMARY KEY (connection_id, chat_id)
);

-- Hamma xabarlar
CREATE TABLE messages (
    id              BIGSERIAL PRIMARY KEY,
    connection_id   TEXT REFERENCES connections(id),
    chat_id         BIGINT,
    from_user_id    BIGINT,
    from_user_name  TEXT,
    message_id      BIGINT,
    direction       TEXT,            -- 'incoming' | 'outgoing'
    content_type    TEXT,            -- 'text' | 'photo' | ...
    text            TEXT,            -- text yoki caption (toza matn)
    media_file_id   TEXT,
    media_file_name TEXT,
    media_mime      TEXT,
    media_duration  INTEGER,
    is_edited       BOOLEAN DEFAULT FALSE,
    is_deleted      BOOLEAN DEFAULT FALSE,
    raw_json        JSONB,           -- butun update
    tg_date         TIMESTAMPTZ,     -- Telegram vaqti
    created_at      TIMESTAMPTZ DEFAULT now(),
    analyzed        BOOLEAN DEFAULT FALSE  -- AI worker shuni belgilab boradi
);

CREATE INDEX idx_messages_conn_chat ON messages (connection_id, chat_id);
CREATE INDEX idx_messages_created    ON messages (created_at);
CREATE INDEX idx_messages_analyzed   ON messages (analyzed);
```

> `analyzed` maydoni — alohida AI worker uchun: u faqat `analyzed = false` xabarlarni
> oladi, ishlatib bo'lgach `true` qiladi. Shu bois bu bot va AI bir-biriga xalal bermaydi.

---

## 7. Logging talablari

Har bir kelgan update **logga chiqsin**. Tavsiya: **JSON formatda** (keyin parse qilish oson).

Har bir log yozuvida bo'lsin:

- vaqt (ISO),
- update turi (`business_connection` / `business_message` / `edited` / `deleted`),
- `connection_id`,
- `chat_id`,
- `from_user_id` va ismi,
- `direction`,
- `content_type`,
- matnning qisqa ko'rinishi (preview, masalan 80 belgigacha).

Qoidalar:

- `INFO` — har bir oddiy xabar.
- `WARNING` — noma'lum content_type yoki kutilmagan holat.
- `ERROR` — bazaga yozishda xato (lekin bot ishdan to'xtamasin, log qilsin va davom etsin).
- Log fayli **rotation** bilan (kunlik yoki o'lchamga qarab), hamda konsolga ham chiqsin.

---

## 8. Arxitektura qoidalari

1. Xabar kelganda — **tez bazaga yoz, vassalom**. Hech qanday AI/og'ir ish yo'q.
2. Bazaga yozish **async**. Xato bo'lsa: log + (ixtiyoriy) qayta urinish. Bot to'xtamasin.
3. Bu bot AI'ni **chaqirmaydi**. AI worker — butunlay alohida jarayon/server, bazadan o'qiydi.
4. Yuk yengil: 100+ akkaunt, sekundiga bir necha xabar — bu aiogram uchun juda kichik yuk.
5. Polling bilan boshla; kengaytirganda webhook'ga o'tkaz.

---

## 9. Konfiguratsiya (.env)

```
BOT_TOKEN=...            # @BotFather, Business Mode yoqilgan bot
DATABASE_URL=postgresql://user:pass@host:5432/dbname
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log
```

Hech qanday parol/token kodda yozilmasin — faqat env orqali.

---

## 10. Botni tayyorlash (BotFather)

1. `@BotFather` → bot yarat → token ol.
2. Bot Settings → **Business Mode → Turn on**.
3. Xodim: Settings → Business → Chatbots (yoki Chat Automation) → bot username'ini qo'shadi.
4. Xodim qaysi chatlarni qo'shishni tanlaydi (shaxsiy/kontaktlarni **chiqarib tashlash** tavsiya etiladi).
5. Javob ruxsati (reply) — **berilmasin** (bizga faqat o'qish kerak).

---

## 11. Muhim nuanslar / cheklovlar

- Bot **ulangan paytdan keyingi** yangi xabarlarni oladi — eski tarixni emas.
- "Qaysi chatlarga ruxsat berilgan" ro'yxatini Bot API **bermaydi**; chatlar xabar kelgani
  sayin kashf qilinadi (`chats` jadvali shu uchun).
- Bot **o'zi va boshqa botlar** yuborgan xabarlarni olmaydi.
- `raw_json` doim saqlansin — kelajakda yangi maydon kerak bo'lsa, qayta ishlovga asos bo'ladi.
- Premium/Business talabi akkaunt tomonida bo'lishi mumkin — buni 1-2 test akkauntda
  oldindan tekshirish kerak (bu bot kodiga taalluqli emas).

---

## 12. Qabul mezoni (bot tayyor deyish uchun)

- [ ] To'rtala business update turi ushlanadi.
- [ ] Yangi connection `connections` jadvaliga tushadi, log ko'rinadi.
- [ ] Har xil turdagi xabar (text, photo, voice, document, ...) to'g'ri `content_type` bilan saqlanadi.
- [ ] `direction` to'g'ri aniqlanadi (mijoz/xodim).
- [ ] `text`/`caption` toza maydonda, `raw_json` to'liq saqlanadi.
- [ ] Har bir xabar logga chiqadi.
- [ ] Bazaga yozishda xato bo'lsa, bot to'xtamaydi (log qiladi, davom etadi).
- [ ] Bot hech kimga javob yozmaydi.

---

## 13. DEBUG / TEST rejimi (birinchi navbatda shuni qil)

Kod yozishni **shu rejimdan boshla**. Maqsad: userdan/chatdan **qanday ma'lumotlar
kelishini ko'rish**, ya'ni tahlil uchun nima borligini bilib olish. Bu rejimda baza
ham, AI ham kerak emas — **faqat to'liq log**.

Talablar:

1. Bot hech kimga javob yozmaydi, hech narsa o'zgartirmaydi — **faqat o'qiydi va logga to'kadi**.
2. To'rtala business update kelganda (`business_connection`, `business_message`,
   `edited_business_message`, `deleted_business_messages`) **ikki narsa** logga chiqsin:
   - **Qisqa xulosa** (tez o'qish uchun): update turi, `content_type`, `direction`
     (mijoz/xodim), `connection_id`, `chat_id`, kim yozgani (id, ism, username),
     va matnning qisqa ko'rinishi (~80 belgi).
   - **To'liq JSON** — update obyektining **hamma maydoni**. aiogram (pydantic) uchun:
     `obj.model_dump_json(indent=2, exclude_none=True, by_alias=True)`.
     - `exclude_none=True` — faqat **mavjud** maydonlar chiqadi, shunda nima bor / nima
       yo'qligi darrov ko'rinadi.
     - `by_alias=True` — Telegramdagi haqiqiy maydon nomlari ko'rinadi (masalan `from`).
3. Log ham **konsolga**, ham **faylga** (`logs/debug_bot.log`, rotation bilan) chiqsin.
4. `direction` aniqlash: connection egasining (xodim) `user.id` ni `business_connection`
   update'idan eslab qol; xabarda `from_user.id == owner_id` bo'lsa **outgoing (xodim)**,
   aks holda **incoming (mijoz)**. Bot qayta ishga tushsa, kerak bo'lsa
   `get_business_connection` orqali egani aniqla.
5. Polling'da `business_*` updatelar olinishi uchun `allowed_updates` ga ular qo'shilsin
   (aiogram'da `dp.resolve_used_update_types()` registratsiya qilingan handlerlar bo'yicha
   avtomatik aniqlaydi).

Test qadami: har xil turdagi xabar yuborib ko'r — **text, photo, voice, video, document,
sticker, contact, location** — har biriga qanday maydonlar (ayniqsa `file_id`, `caption`,
`duration`, va h.k.) kelishini logdan ko'r. Aynan shu ro'yxat keyin 5.2 va 6-bandlardagi
saqlash sxemasini yakuniy aniqlashga asos bo'ladi.

> Shu debug rejimi ishlab, ma'lumotlar to'liq ko'ringandan keyingina 6-banddagi bazaga
> yozishga o'tiladi.
