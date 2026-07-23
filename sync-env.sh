#!/usr/bin/env bash
#
# Lokal .env ni serverga yuklab, botni yangi qiymatlar bilan qayta ishga tushiradi.
# Ishlatish:  ./sync-env.sh
#
# .env git'ga kirmaydi (gitignore) — shuning uchun uni alohida shu skript bilan
# serverga yuboramiz. Kod uchun esa oddiy `git push` (CI/CD) yetarli.

set -euo pipefail

# --- Server sozlamalari (yangi serverga o'tsangiz shularni o'zgartiring) ---
SERVER_USER="ikpydev"
SERVER_HOST="89.167.30.131"
SERVER_PORT="5522"
REMOTE_DIR="~/bot"
# --------------------------------------------------------------------------

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "❌ .env fayli topilmadi (shu papkada bo'lishi kerak)."
  exit 1
fi

echo "📤 .env serverga yuklanmoqda ($SERVER_HOST)..."
scp -P "$SERVER_PORT" .env "$SERVER_USER@$SERVER_HOST:$REMOTE_DIR/.env"

echo "🔄 Bot yangi qiymatlar bilan qayta ishga tushmoqda..."
ssh -p "$SERVER_PORT" "$SERVER_USER@$SERVER_HOST" "cd $REMOTE_DIR && docker compose up -d"

echo "✅ Tayyor. Loglarni ko'rish uchun:"
echo "   ssh -p $SERVER_PORT $SERVER_USER@$SERVER_HOST 'cd $REMOTE_DIR && docker compose logs -f bot'"
