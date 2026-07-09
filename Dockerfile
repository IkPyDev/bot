FROM python:3.13-slim

# Log'lar bufferlanmasin — journal/compose'da darhol ko'rinsin
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Avval faqat requirements — Docker layer cache uchun (kod o'zgarsa qayta pip install bo'lmaydi)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Qolgan kod
COPY . .

# Log papkasi (LOG_FILE=logs/bot.log uchun)
RUN mkdir -p logs

CMD ["python", "main.py"]
