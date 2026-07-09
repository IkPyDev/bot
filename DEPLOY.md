# Deploy qo'llanmasi (runbook)

Bu fayl botni **yangi serverga noldan** deploy qilish va CI/CD sozlashning to'liq
tartibini beradi. Bir marta bajarilgan ishlar shu yerda hujjatlashtirilgan.

---

## 0. Arxitektura (qisqa)

- Bot **polling** rejimda ishlaydi → domen/ochiq port/nginx **kerak emas**.
- Docker Compose 2 ta xizmat ko'taradi: `bot` (Python) + `db` (PostgreSQL 16).
- Ma'lumot `pgdata` nomli **volume**da saqlanadi — konteyner qayta qurilsa yo'qolmaydi.
- Jadvallar `db.connect()` da avtomatik yaratiladi (`CREATE TABLE IF NOT EXISTS`).
- **Muhim:** bot bir vaqtda faqat BITTA joyda ishlashi shart (token bitta).
  Ikki joyda ishlasa `TelegramConflictError`.

---

## 1. Hozirgi (production) server ma'lumotlari

| Narsa | Qiymat |
|-------|--------|
| Provayder | Hetzner (ubuntu-4gb-hel1-1) |
| IPv4 | `89.167.30.131` |
| SSH | `ssh -p 5522 ikpydev@89.167.30.131` (port **5522**, 22 emas) |
| User | `ikpydev` (`docker` guruhida, sudo bor) |
| Kod joylashuvi | `/home/ikpydev/bot/` |
| GitHub repo | `git@github.com:IkPyDev/bot.git` (private) |
| Bot | @sirsaqlauzbot (id 8604268218) |

> Yangi serverga o'tsangiz, shu jadvalni yangilang va CI/CD secret'larini yangi
> server qiymatlari bilan almashtiring (pastda).

---

## 2. Yangi serverga noldan deploy — qadamlar

### 2.1. Server tayyorligi
Yangi Ubuntu server (oddiy user + SSH kirish). Serverga SSH bilan kiring.

### 2.2. Docker o'rnatish (serverda)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# guruh kuchga kirishi uchun SSH'dan chiqib qayta kiring:
exit
```
Qayta kirgach tekshiring (sudo'siz ishlashi kerak):
```bash
docker ps
docker --version && docker compose version
```

### 2.3. Kodni serverga yuborish
Ikki usuldan birini tanlang:

**A) Git orqali** (repo public bo'lsa yoki deploy key sozlangan bo'lsa):
```bash
cd ~ && git clone git@github.com:IkPyDev/bot.git bot && cd bot
```

**B) Mac'dan rsync orqali** (git'siz):
```bash
# Mac'da, loyiha papkasida:
rsync -az --delete -e 'ssh -p PORT' \
  --exclude '.venv' --exclude '__pycache__' --exclude '.idea' \
  --exclude 'logs' --exclude 'data' --exclude '.env' --exclude '.DS_Store' \
  ./ USER@NEW_SERVER_IP:/home/USER/bot/
```

### 2.4. `.env` faylni yaratish (serverda) — ⚠️ ENG MUHIM QADAM
`.env` git'ga KIRMAYDI (`.gitignore`da), shuning uchun har serverda **qo'lda** yaratiladi.
`.env.example` dan nusxa oling va to'ldiring:
```bash
cd ~/bot && cp .env.example .env && nano .env
```
E'tibor bering:
- `DATABASE_URL` da host = **`db`** (compose xizmat nomi), `localhost` EMAS.
- `POSTGRES_USER/PASSWORD/DB` — `DATABASE_URL` dagi bilan bir xil bo'lsin.
- Parolda **maxsus belgi ishlatmang** (`$ @ : / ! # ?`) — `.env`/compose
  interpolatsiyasi va URL'ni buzadi. Faqat harf + raqam.
  Xavfsiz parol: `LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 28; echo`

`.env` namunasi (Docker uchun):
```
BOT_TOKEN=<botfather_token>
POSTGRES_USER=botuser
POSTGRES_PASSWORD=<faqat_harf_raqam_parol>
POSTGRES_DB=botdb
DATABASE_URL=postgresql://botuser:<xuddi_shu_parol>@db:5432/botdb
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log
ADMIN_IDS=<telegram_id>
CHANNEL_ID=<kanal_id>
MEDIA_CHANNEL_ID=<kanal_id>
START_MEDIA_MESSAGE_ID=3
CONNECT_MEDIA_MESSAGE_ID=2
```

### 2.5. Ishga tushirish (serverda)
```bash
cd ~/bot
docker compose up -d --build
docker compose logs -f bot
```
Log'da quyidagilar chiqsa — muvaffaqiyat:
- `PostgreSQL pool connected`
- `Migrations applied successfully`
- `Bot started successfully. PostgreSQL connected.`
- `Bot info: id=..., username=@...`

> ⚠️ Agar `TelegramConflictError` chiqsa — bot boshqa joyda ham ishlayapti.
> Eski nusxani (eski server yoki lokal `docker compose down`) to'xtating.

---

## 3. CI/CD (GitHub Actions) — yangi server uchun sozlash

Workflow fayli: `.github/workflows/deploy.yml` (easingthemes/ssh-deploy).
`main` branch'ga har `git push` bo'lganda serverga rsync qiladi + `docker compose up -d --build`.

### 3.1. Actions → server uchun deploy kaliti yaratish
Mac'da (yoki istalgan joyda) **parolsiz** ed25519 kalit yarating:
```bash
ssh-keygen -t ed25519 -f actions_deploy -N "" -C "github-actions-deploy"
```
Ochiq qismini (`actions_deploy.pub`) yangi serverning `~/.ssh/authorized_keys` ga qo'shing:
```bash
ssh -p PORT USER@NEW_SERVER_IP "cat >> ~/.ssh/authorized_keys" < actions_deploy.pub
```

### 3.2. GitHub Secrets qo'shish
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Qiymat |
|--------|--------|
| `SSH_HOST` | yangi server IP |
| `SSH_PORT` | SSH port (masalan `5522` yoki `22`) |
| `SSH_USER` | serverdagi user |
| `SSH_KEY` | `actions_deploy` **maxfiy** kaliti (BEGIN...END gacha to'liq) |

### 3.3. `deploy.yml` dagi TARGET
Agar serverdagi user/yo'l boshqacha bo'lsa, `.github/workflows/deploy.yml` da
`TARGET: "/home/ikpydev/bot/"` qiymatini yangi yo'lga o'zgartiring.

### 3.4. Sinash
```bash
git commit --allow-empty -m "test deploy" && git push
```
`https://github.com/IkPyDev/bot/actions` da yashil ✅ bo'lsa — CI/CD ishlaydi.

---

## 4. Kundalik ishlatish

**Yangilash (kod o'zgargach):**
```bash
git add -A && git commit -m "..." && git push   # → avtomatik deploy
```

**Serverni boshqarish** (SSH bilan kirib, `cd ~/bot`):
```bash
docker compose logs -f bot     # jonli log
docker compose ps              # holat
docker compose restart bot     # qayta ishga tushirish
docker compose down            # to'xtatish (ma'lumot saqlanadi)
docker compose up -d           # qayta yoqish
docker compose down -v         # ⚠️ ma'lumotni HAM o'chiradi
```

---

## 5. Eslatmalar / xatoliklar (troubleshooting)

| Muammo | Sabab / yechim |
|--------|----------------|
| `TelegramConflictError` | Bot ikki joyda ishlayapti. Faqat bittasini qoldiring |
| `password authentication failed` | `.env` da `DATABASE_URL` paroli ≠ `POSTGRES_PASSWORD`, yoki parolda maxsus belgi bor |
| Bot bazaga ulanmaydi | `DATABASE_URL` hosti `localhost` bo'lib qolgan — `db` bo'lishi kerak |
| Deploy ma'lumotni o'chirib yubordimi? | Yo'q. `up -d --build` faqat `bot`ni qayta quradi, `db`/`pgdata` tegilmaydi |
| Actions xato: SSH ulanmadi | Secret'lar (HOST/PORT/USER/KEY) noto'g'ri yoki ochiq kalit serverda yo'q |
| Server qayta yuklandi, bot to'xtadimi? | Yo'q. `restart: always` — Docker o'zi qaytaradi |

---

## 6. Yangi serverga ko'chirish — tez checklist

- [ ] Yangi serverga Docker o'rnatildi (`get.docker.com`), user `docker` guruhida
- [ ] Kod serverda (`git clone` yoki `rsync`)
- [ ] `.env` yaratildi (host=`db`, parol maxsus belgisiz, token/kanal'lar to'g'ri)
- [ ] Eski server/lokaldagi bot to'xtatildi (token conflict bo'lmasin)
- [ ] `docker compose up -d --build` → loglar toza
- [ ] Actions deploy kaliti yangi serverga qo'shildi
- [ ] GitHub Secrets yangi server qiymatlari bilan yangilandi
- [ ] `deploy.yml` TARGET yo'li to'g'ri
- [ ] `git push` bilan CI/CD sinovdan o'tdi (yashil ✅)
- [ ] Bu faylning 1-bo'limi (server ma'lumotlari) yangilandi
