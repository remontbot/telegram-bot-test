from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ВСТАВЬ СВОЙ АКТУАЛЬНЫЙ ТОКЕН ОТ BotFather ВМЕСТО ХХХ
TOKEN = "8578914807:AAG3wbCPRJ7DtL0QbLPhNOMxSB-KULofjHw"  # типа "8578914807:AAFRlymGjiuqu5K0eq3UVPtGLMUV_UQmCI0"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Бот для поиска работников запущен ✅")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
