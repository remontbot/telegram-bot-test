import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

# ВСТАВЬ сюда токен, который сейчас в Railway / BotFather.
HARDCODED_TOKEN = "8578914807:AAFRlymGjiuqu5K0eq3UVPtGLMUV_UQmCI0"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Бот для поиска работников запущен ✅")

def main():
    # Сначала пробуем взять из env, если нет — берём из HARDCODED_TOKEN
    token = os.getenv("BOT_TOKEN") or HARDCODED_TOKEN
    logging.info(f"Read BOT_TOKEN from env or hardcoded: {repr(token)}")

    if not token:
        raise RuntimeError("Нет токена для запуска бота")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
