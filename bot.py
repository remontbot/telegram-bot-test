import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

print("--- Environment Variables ---")
for key, value in os.environ.items():
    print(f"{key}={value}")
print("----------------------------")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Бот для поиска работников запущен ✅")

def main():
    token = os.getenv("BOT_TOKEN")
    logging.info(f"BOT_TOKEN from os.getenv: {repr(token)}")

    if not token:
        raise RuntimeError("Переменная окружения BOT_TOKEN не установлена")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
