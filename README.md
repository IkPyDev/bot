# Telegram Business Bot (@sirsaqlauzbot)

Telegram **Business** akkauntlariga ulanadigan bot. Ulangan biznes akkauntga kelgan/ketgan
xabarlarni ushlab **PostgreSQL** bazaga yozadi, xabar o'chirilsa/tahrirlansa kanalga
bildirishnoma yuboradi. Bot foydalanuvchilarga javob **yozmaydi** — faqat kuzatadi va saqlaydi.

## Nima qiladi

- **business_connection** — biznes akkaunt ulanishi/o'chishini kuzatadi (`connection.py`)
- **business_message** — har bir xabarni bazaga yozadi, 12 xil content-type'ni ajratadi (`message.py`)
- **edited_business_message** — tahrirlangan xabarni aniqlaydi, eski/yangi matnni kanalga yuboradi (`edited.py`)
- **deleted_business_messages** — o'chirilgan xabar matnini **bazadan tiklab** kanalga xabar beradi (`deleted.py`)
- **/start** — ulangan foydalanuvchiga xush kelibsiz xabari + media (`start.py`)
- **/reklama** — adminlar uchun broadcast (FSM asosida) (`admin.py`)
- **Kunlik backup** — har kuni belgilangan vaqtda log + DB dump'ni backup kanaliga yuboradi (`scheduler.py`)

## Texnologiyalar

| Qism | Tanlov |
|------|--------|
| Til | Python 3.13 |
| Framework | aiogram 3.29 (polling rejim) |
| Baza | PostgreSQL 16 (asyncpg, connection pool min=2/max=10) |
| Konteyner | Docker + Docker Compose |
| Log | JSON strukturali log (`logger.py`) |

## Loyiha strukturasi

```
bot/
├── main.py                 # Kirish nuqtasi — dispatcher, polling, startup/shutdown
├── app/
│   ├── config.py           # .env dan sozlamalarni o'qish
│   ├── db.py               # PostgreSQL wrapper (pool, CRUD, avtomatik migratsiya)
│   ├── logger.py           # JSON log + QueueHandler
│   ├── middlewares.py      # Har qanday update'ni logga yozuvchi middleware
│   ├── extractors.py       # Xabardan maydonlarni ajratish
│   ├── scheduler.py        # Kunlik backup rejasi
│   └── handlers/           # Update turlariga qarab handlerlar
│       ├── connection.py   # business_connection
│       ├── message.py      # business_message (eng muhim)
│       ├── edited.py       # edited_business_message
│       ├── deleted.py      # deleted_business_messages
│       ├── start.py        # /start
│       └── admin.py        # /reklama broadcast
├── migrations/
│   └── 002_init_postgres.sql   # Jadvallar (connect() da avtomatik qo'llanadi)
├── Dockerfile
├── docker-compose.yml      # bot + db (postgres) xizmatlari
└── .env                    # Sozlamalar (git'ga KIRMAYDI)
```

## Sozlamalar (.env)

`.env.example` dan nusxa oling. Muhim o'zgaruvchilar:

| O'zgaruvchi | Tavsif |
|-------------|--------|
| `BOT_TOKEN` | @BotFather token (Business rejim yoqilgan) |
| `POSTGRES_USER/PASSWORD/DB` | Postgres konteyneri sozlamalari |
| `DATABASE_URL` | DSN — **Docker'da host = `db`**, `localhost` emas. Paroli `POSTGRES_*` bilan bir xil |
| `ADMIN_IDS` | Reklama yuboradigan adminlar (vergul bilan) |
| `CHANNEL_ID` | Bildirishnoma/forward kanali |
| `MEDIA_CHANNEL_ID`, `*_MESSAGE_ID` | /start va ulanish media'si turgan kanal |
| `LOG_LEVEL`, `LOG_FILE` | Log darajasi va fayli |

> ⚠️ Parolda maxsus belgi (`$ @ : / ! # ?`) ishlatmang — `.env`/compose interpolatsiyasi va URL'ni buzadi. Faqat harf + raqam.

## Ishga tushirish (Docker)

```bash
docker compose up -d --build      # build + ishga tushirish
docker compose logs -f bot        # jonli log
docker compose ps                 # holat
```

Postgres jadvallari `connect()` da avtomatik yaratiladi (`CREATE TABLE IF NOT EXISTS`) —
qo'lda migratsiya shart emas.

## Boshqarish

```bash
docker compose restart bot        # qayta ishga tushirish
docker compose down               # to'xtatish (ma'lumot saqlanadi)
docker compose up -d              # qayta yoqish
docker compose down -v            # ⚠️ ma'lumotni HAM o'chiradi (pgdata volume)
```

Ma'lumot `pgdata` nomli volume'da saqlanadi — konteyner qayta qurilsa/o'chsa ham yo'qolmaydi.
Faqat `down -v` volume'ni o'chiradi.

## Muhim eslatmalar

- **Bot faqat BITTA joyda** ishlashi kerak (polling, token bitta). Ikki joyda ishlasa
  `TelegramConflictError` beradi. Serverda ishlayotgan bo'lsa, lokalda ishga tushirmang.
- `restart: always` — server qayta yuklansa yoki bot yiqilsa Docker o'zi qaytaradi.
- Mavjud jadvalga **yangi ustun** qo'shsangiz, `IF NOT EXISTS` uni o'zgartirmaydi —
  `ALTER TABLE` migratsiyasi qo'shing.

## Deploy

Hozir **Hetzner Ubuntu serverida** Docker orqali 24/7 ishlaydi. Qo'lda yangilash:

```bash
# Mac'dan kodni yuborish
rsync -az --delete -e 'ssh -p 5522' \
  --exclude '.venv' --exclude '__pycache__' --exclude 'logs' --exclude 'data' \
  ./ ikpydev@SERVER_IP:/home/ikpydev/bot/
# Serverda qayta qurish
ssh -p 5522 ikpydev@SERVER_IP 'cd ~/bot && docker compose up -d --build'
```

CI/CD (GitHub Actions) sozlansa, bu jarayon `git push` bilan avtomatlashtiriladi.
