# Telegram Business Bot (@sirsaqlauzbot)

Telegram **Business** akkauntlariga ulanadigan bot. Ulangan biznes akkauntga kelgan/ketgan
xabarlarni ushlab **PostgreSQL** bazaga yozadi, xabar o'chirilsa/tahrirlansa egasiga va
kanalga bildirishnoma yuboradi. Bot mijozlarga javob **yozmaydi** — faqat kuzatadi va saqlaydi.

> Ulash uchun Telegram Premium **shart emas** — oddiy akkauntlarda ham ishlaydi.

## Nima qiladi

| Update / komanda | Fayl | Vazifasi |
|---|---|---|
| `business_connection` | `connection.py` | Ulanish/o'chishni kuzatadi, egasiga qo'llanma video yuboradi |
| `business_message` | `message.py` | Har xabarni bazaga yozadi, kanalga nusxalaydi (12 content-type) |
| `edited_business_message` | `edited.py` | Tahrirni aniqlaydi, **eski/yangi** matnni ko'rsatadi |
| `deleted_business_messages` | `deleted.py` | O'chirilgan xabarni **bazadan tiklab** yuboradi |
| `/start` | `start.py` | Xush kelibsiz media + ulash tugmalari |
| `/reklama` | `admin.py` | Adminlar uchun broadcast (FSM) |
| Kunlik backup | `scheduler.py` | Log + `pg_dump` ni backup kanaliga yuboradi |

## Asosiy oqim (business_message)

Xabar kelganda [message.py](app/handlers/message.py) quyidagi tartibda ishlaydi:

1. **content_type** aniqlanadi (`extractors.py` — text/photo/video/voice/video_note/audio/
   document/sticker/contact/location/venue/poll, aniqlanmasa `unknown`).
2. **direction** aniqlanadi: yuboruvchi = connection egasi bo'lsa `outgoing` (xodim→mijoz),
   aks holda `incoming` (mijoz→xodim). Egasining ID si in-memory cache'da, yo'q bo'lsa
   `get_business_connection` API orqali olinadi.
3. Agar **himoyalangan (protected) mediaga reply** qilingan bo'lsa va u media **mijoznikiga**
   tegishli bo'lsa — egasining lichkasiga nusxasi yuboriladi (pastda "Himoyalangan media" bo'limi).
4. Xabar `messages` jadvaliga yoziladi (`raw_json` — butun update JSONB sifatida).
5. Kanalga nusxa **navbatga qo'yiladi** (to'g'ridan yuborilmaydi — pastda "Kanal navbati").
6. `chats` jadvali yangilanadi.

**Bildirishnomalar qayerga boradi:**

- **Kanal** (`CHANNEL_ID`) — **hamma narsa**: har bir xabar, har bir tahrir, har bir o'chirish.
  Sarlavhada: kimdan → kimga (bosiladigan havola + `@username` + `[ID]`), tur, vaqt, file_id.
- **Egasining lichkasi** — **faqat mijoz tomonidan** qilingan tahrir/o'chirish
  (`direction == "incoming"`). O'zi tahrirlagan/o'chirgan xabari uchun bildirishnoma kelmaydi.

## /start va ulash tugmalari

`/start` bosilganda `MEDIA_CHANNEL_ID` kanalidagi media `copy_message` bilan olinib,
`START_CAPTION` va uchta tugma bilan yuboriladi:

| Tugma | Nima qiladi |
|---|---|
| 🔌 Ulash | `tg://settings/edit` — Telegram sozlamalarini ochadi |
| 🤖 Android ulash | `ANDROID_MEDIA_MESSAGE_ID` videosi + Android qo'llanmasi |
| 🍏 iOS ulash | `IOS_MEDIA_MESSAGE_ID` videosi + iOS qo'llanmasi |

Android/iOS tugmalari `callback_data="howto:<platforma>"` orqali
[`on_howto`](app/handlers/start.py) handleriga tushadi. Ikkala ID ham sozlanmasa —
`START_MEDIA_MESSAGE_ID` ishlatiladi (default).

> Botga lichkada rasm/video yuborilsa, bot javoban uning **file_id** sini qaytaradi
> (`on_private_message`). Bu ID olish uchun qulay, lekin **hamma foydalanuvchiga** ishlaydi.

## Himoyalangan (protected) media

Telegram `has_protected_content=true` bo'lgan xabarni bot to'g'ridan-to'g'ri yuklab ololmaydi.
Yagona yo'l — **reply konteksti**: xodim o'sha mediaga (ochishdan oldin!) istalgan xabar bilan
javob yozsa, bot uni `reply_to_message` ichida ko'radi va lichkaga nusxalaydi.

Ikki bosqichli yuborish ([`_send_copy_to_owner`](app/handlers/message.py)):

1. **file_id bilan to'g'ridan** — yuklab olish yo'q, shuning uchun 20 MB cheklovi yo'q,
   katta videolar ham o'tadi.
2. Ishlamasa — **yuklab olib qayta yuborish** (faqat <20 MB).

Egasi **o'z** protected xabariga reply qilsa — saqlanmaydi (faqat mijozniki).

## Barqarorlik mexanizmlari

Bu qismlar bot yiqilmasligi va RAM/flood muammosi bo'lmasligi uchun qo'yilgan:

- **Kanal navbati** — har xabar to'g'ridan kanalga emas, `asyncio.Queue` ga (maxsize **1000**)
  qo'yiladi. Bitta fon worker ketma-ket yuboradi, `TelegramRetryAfter` (429) bo'lsa kutib bir
  marta qayta uriniladi. Navbat to'lsa — yangi job **tashlanadi** (bot to'xtamaydi).
- **Yuklash semafori** — bir vaqtda maksimum **5** parallel fayl yuklash (`_MAX_PARALLEL_DOWNLOADS`).
- **tasks_concurrency_limit=100** — polling'da bir vaqtda ishlaydigan handler tasklar chegarasi.
- **Media fallback** — kanal/xabar topilmasa yoki bot a'zo bo'lmasa, matn bilan yuboriladi va
  logga `warning` yoziladi.

## Texnologiyalar

| Qism | Tanlov |
|------|--------|
| Til | Python 3.13 (`python:3.13-slim`) |
| Framework | aiogram 3.x — hozir 3.29, `requirements.txt` da `>=3.10,<4.0` (polling, `parse_mode="HTML"` default) |
| Baza | PostgreSQL 16 (asyncpg, pool min=2/max=10) |
| Konteyner | Docker + Docker Compose |
| Log | JSON strukturali log, kunlik fayl (`logger.py`) |

## Loyiha strukturasi

```
bot/
├── main.py                 # Kirish nuqtasi — dispatcher, polling, startup/shutdown
├── app/
│   ├── config.py           # .env dan sozlamalarni o'qish (frozen dataclass)
│   ├── db.py               # PostgreSQL wrapper (pool, CRUD, avtomatik migratsiya)
│   ├── logger.py           # JSON log + QueueHandler + kunlik fayl
│   ├── middlewares.py      # Har qanday update'ni logga yozuvchi middleware
│   ├── extractors.py       # content_type / matn / media / direction ajratish
│   ├── scheduler.py        # Kunlik backup (log + pg_dump)
│   └── handlers/
│       ├── __init__.py     # Routerlar tartibi (admin → start → business)
│       ├── connection.py   # business_connection + owner cache
│       ├── message.py      # business_message (eng muhim) + kanal navbati
│       ├── edited.py       # edited_business_message
│       ├── deleted.py      # deleted_business_messages
│       ├── start.py        # /start, ulash tugmalari, file_id yordamchisi
│       └── admin.py        # /reklama broadcast
├── migrations/
│   ├── 001_init.sql            # (eski SQLite varianti)
│   └── 002_init_postgres.sql   # Jadvallar — connect() da avtomatik qo'llanadi
├── Dockerfile
├── docker-compose.yml      # bot + db (postgres) xizmatlari
└── .env                    # Sozlamalar (git'ga KIRMAYDI)
```

## Ma'lumotlar bazasi

| Jadval | Nima saqlaydi |
|---|---|
| `connections` | Botni ulagan xodimlar (connection_id, user_id, user_chat_id, is_enabled) |
| `chats` | Kashf qilingan chatlar (connection_id + chat_id) |
| `messages` | Hamma xabarlar — matn, media_file_id, direction, `raw_json` (JSONB), `is_edited`, `is_deleted`, `analyzed` |
| `bot_users` | `/start` bosgan yoki botni ulagan userlar (reklama uchun) |

Xabarlar **o'chirilmaydi** — `is_deleted=TRUE` qilib belgilanadi, tarix qoladi.
Tahrirda eski versiya `is_edited=TRUE` bo'ladi va yangi qator qo'shiladi.

## Sozlamalar (.env)

`.env.example` dan nusxa oling.

| O'zgaruvchi | Tavsif |
|-------------|--------|
| `BOT_TOKEN` | @BotFather token (Business rejim yoqilgan) |
| `DATABASE_URL` | DSN — **Docker'da host = `db`**, `localhost` emas |
| `POSTGRES_USER/PASSWORD/DB` | Postgres konteyneri sozlamalari (DSN bilan mos bo'lsin) |
| `ADMIN_IDS` | `/reklama` yuboradigan adminlar (vergul bilan) |
| `CHANNEL_ID` | Bildirishnoma/nusxa kanali |
| `BACKUP_CHANNEL_ID` | Kunlik backup kanali (sozlanmasa `CHANNEL_ID`) |
| `BACKUP_TIME` | Backup vaqti `HH:MM`, default `00:30` |
| `MEDIA_CHANNEL_ID` | Media turgan "database" kanal — **bot a'zo/admin bo'lishi shart** |
| `START_MEDIA_MESSAGE_ID` | `/start` media xabar ID si |
| `CONNECT_MEDIA_MESSAGE_ID` | Ulanish qo'llanma videosi ID si |
| `ANDROID_MEDIA_MESSAGE_ID` | "Android ulash" videosi ID si (sozlanmasa — start videosi) |
| `IOS_MEDIA_MESSAGE_ID` | "iOS ulash" videosi ID si (sozlanmasa — start videosi) |
| `LOG_LEVEL`, `LOG_FILE` | Log darajasi va fayli |

> ⚠️ Parolda maxsus belgi (`$ @ : / ! # ?`) ishlatmang — `.env`/compose interpolatsiyasi va
> URL'ni buzadi. Faqat harf + raqam.

## Ishga tushirish (Docker)

```bash
docker compose up -d --build      # build + ishga tushirish
docker compose logs -f bot        # jonli log
docker compose ps                 # holat
```

Jadvallar `connect()` da avtomatik yaratiladi (`CREATE TABLE IF NOT EXISTS`) —
qo'lda migratsiya shart emas.

## Boshqarish

```bash
docker compose restart bot        # qayta ishga tushirish (.env o'zgarsa — shart)
docker compose down               # to'xtatish (ma'lumot saqlanadi)
docker compose up -d              # qayta yoqish
docker compose down -v            # ⚠️ ma'lumotni HAM o'chiradi (pgdata volume)
```

Ma'lumot `pgdata` volume'da — konteyner qayta qurilsa ham yo'qolmaydi. Faqat `down -v` o'chiradi.

## Kunlik backup

Har kuni `BACKUP_TIME` da (mahalliy vaqt) **kechagi** log fayli va `pg_dump` gzip qilinib
backup kanaliga yuboriladi. Log fayllari serverda **qoladi** (o'chirilmaydi).

- `pg_dump` PATH da bo'lishi kerak (`postgresql-client`) — bo'lmasa DB backup o'tkazib yuboriladi.
- Telegram limiti **50 MB**; oshsa fayl o'rniga ogohlantirish yuboriladi.

## Muhim eslatmalar

- **Bot faqat BITTA joyda** ishlashi kerak (polling, token bitta). Ikki joyda ishlasa
  `TelegramConflictError`. Serverda ishlayotgan bo'lsa, lokalda ishga tushirmang.
- Bot **faqat ulangandan keyingi** xabarlar bilan ishlaydi — eski yozishmalar ko'rinmaydi.
- O'chirish eventida Telegram **na kim o'chirganini, na matnni** beradi — faqat `message_id`.
  Shuning uchun matn bazadan tiklanadi; bazada bo'lmasa "matn topilmadi" deb ketadi.
- Cache'lar **in-memory** — bot restart bo'lsa bo'shaydi, lekin API orqali qayta tiklanadi.
- Mavjud jadvalga **yangi ustun** qo'shsangiz, `IF NOT EXISTS` uni o'zgartirmaydi —
  `ALTER TABLE` migratsiyasi qo'shing.

## Deploy

Hozir **Hetzner Ubuntu serverida** Docker orqali 24/7 ishlaydi va **CI/CD** sozlangan:
`main` branch'ga `git push` qilsangiz, GitHub Actions avtomatik serverga deploy qiladi.

```bash
git add -A && git commit -m "..." && git push   # → avtomatik deploy
```

To'liq deploy qo'llanmasi (yangi serverga noldan ko'chirish, CI/CD sozlash, troubleshooting):
👉 **[DEPLOY.md](DEPLOY.md)**

Loyiha qoidalari (matn yozish, media, Premium) 👉 **[CLAUDE.md](CLAUDE.md)**
