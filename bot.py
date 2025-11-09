import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
import db
import handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    db.init_db()

    token = config.BOT_TOKEN
    if not token:
        logger.error("BOT_TOKEN не установлен")
        raise RuntimeError("BOT_TOKEN не установлен")

    application = ApplicationBuilder().token(token).build()

    # ConversationHandler для регистрации
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", handlers.start_command)],
        states={
            handlers.SELECTING_ROLE: [
                CallbackQueryHandler(
                    handlers.select_role, pattern="^select_role_"
                )
            ],
            # мастер
            handlers.REGISTER_MASTER_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_name,
                )
            ],
            handlers.REGISTER_MASTER_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_phone,
                )
            ],
            handlers.REGISTER_MASTER_CITY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_city,
                )
            ],
            handlers.REGISTER_MASTER_REGIONS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_regions,
                )
            ],
            handlers.REGISTER_MASTER_CATEGORIES_SELECT: [
                CallbackQueryHandler(
                    handlers.register_master_categories_select,
                    pattern="^cat_",
                )
            ],
            handlers.REGISTER_MASTER_CATEGORIES_OTHER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_categories_other,
                )
            ],
            handlers.REGISTER_MASTER_EXPERIENCE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_experience,
                )
            ],
            handlers.REGISTER_MASTER_DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_description,
                )
            ],
            # заказчик
            handlers.REGISTER_CLIENT_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_client_name,
                )
            ],
            handlers.REGISTER_CLIENT_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_client_phone,
                )
            ],
            handlers.REGISTER_CLIENT_CITY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_client_city,
                )
            ],
            handlers.REGISTER_CLIENT_DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_client_description,
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                handlers.handle_invalid_input,
            ),
            CallbackQueryHandler(handlers.handle_invalid_input),
        ],
        allow_reentry=True,
    )

    application.add_handler(reg_conv)

    # Меню мастера/заказчика (отдельные callback-и)
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_worker_menu, pattern="^show_worker_menu$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_client_menu, pattern="^show_client_menu$"
        )
    )

    # Неизвестные команды
    application.add_handler(
        MessageHandler(filters.COMMAND, handlers.unknown_command)
    )

    logger.info("Бот запущен.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
