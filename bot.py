import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

# 🔐 ВСТАВЬ СЮДА АКТУАЛЬНЫЙ ТОКЕН, КОТОРЫЙ СЕЙЧАС ЖИВОЙ У ЭТОГО БОТА
HARDCODED_TOKEN = "ТОКЕН_ОТСЮДА_ИЗ_BOTFATHER"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Бот для поиска работников запущен ✅")

def main():
    env_token = os.getenv("BOT_TOKEN")
    token = env_token or HARDCODED_TOKEN

    logging.info(f"Read BOT_TOKEN from env: {repr(env_token)}")
    logging.info(f"Using token: {repr(token)}")

    if not token:
        raise RuntimeError("Нет токена для запуска бота")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
