import logging
import os

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram import Update

import db
import handlers

# --- НАЧАЛО ИСПРАВЛЕННОГО БЛОКА ДЛЯ ИМПОРТА CONFIG.PY И ЗАГРУЗКИ ENV ---
# Попытка импортировать config, если он есть рядом (локально)
config = None
try:
    import config as local_config
    config = local_config
except ModuleNotFoundError:
    # В Railway или другой среде config.py может не быть — это ок, пойдём через ENV
    pass

# Если локально используешь .env, подхватим (не мешает Railway)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Если python-dotenv не установлен, это не критично для Railway, где ENV уже есть
    pass
# --- КОНЕЦ ИСПРАВЛЕННОГО БЛОКА ---

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_bot_token() -> str:
    """
    1) Если есть config.py и в нём BOT_TOKEN — используем его.
    2) Если нет config.py или нет BOT_TOKEN в нём — берём из переменной окружения BOT_TOKEN.
    """
    # Вариант 1: из config.py
    if config is not None and getattr(config, "BOT_TOKEN", None):
        logger.info("BOT_TOKEN взят из config.py")
        return config.BOT_TOKEN

    # Вариант 2: из ENV (Railway Variables / .env)
    token = os.getenv("BOT_TOKEN")
    if token:
        logger.info("BOT_TOKEN взят из переменных окружения")
        return token

    # Если не нашли вообще — кидаем в лог и падаем с ошибкой
    logger.error("BOT_TOKEN не найден ни в config.py, ни в переменных окружения.")
    raise RuntimeError("BOT_TOKEN не установлен")


def main():
    db.init_db()
    db.migrate_add_portfolio_photos()  # Добавляем колонку если её нет

    token = get_bot_token()

    application = ApplicationBuilder().token(token).build()

    # --- ConversationHandler для регистрации ---

    reg_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", handlers.start_command)],
        states={
            # Выбор роли
            handlers.SELECTING_ROLE: [
                CallbackQueryHandler(handlers.select_role, pattern="^select_role_"),
            ],

            # Регистрация мастера
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
            # Районы больше не используются - переходим сразу к категориям
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
            # ОБНОВЛЕНО: Теперь опыт выбирается кнопками
            handlers.REGISTER_MASTER_EXPERIENCE: [
                CallbackQueryHandler(
                    handlers.register_master_experience,
                    pattern="^exp_",
                )
            ],
            handlers.REGISTER_MASTER_DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_description,
                )
            ],
            # НОВОЕ: Обработка фото работ
            handlers.REGISTER_MASTER_PHOTOS: [
                CallbackQueryHandler(
                    handlers.register_master_photos,
                    pattern="^add_photos_",
                ),
                MessageHandler(
                    filters.PHOTO | filters.TEXT,
                    handlers.handle_master_photos,
                ),
            ],

            # Регистрация заказчика
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

    application.add_handler(reg_conv_handler)

    # --- ConversationHandler для редактирования профиля ---
    
    edit_profile_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.show_edit_profile_menu, pattern="^edit_profile_menu$")
        ],
        states={
            handlers.EDIT_PROFILE_MENU: [
                CallbackQueryHandler(handlers.edit_name_start, pattern="^edit_name$"),
                CallbackQueryHandler(handlers.edit_phone_start, pattern="^edit_phone$"),
                CallbackQueryHandler(handlers.edit_city_start, pattern="^edit_city$"),
                CallbackQueryHandler(handlers.edit_categories_start, pattern="^edit_categories$"),
                CallbackQueryHandler(handlers.edit_experience_start, pattern="^edit_experience$"),
                CallbackQueryHandler(handlers.edit_description_start, pattern="^edit_description$"),
            ],
            handlers.EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_name_save),
            ],
            handlers.EDIT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_phone_save),
            ],
            handlers.EDIT_CITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_city_save),
            ],
            handlers.EDIT_CATEGORIES_SELECT: [
                CallbackQueryHandler(handlers.edit_categories_select, pattern="^editcat_"),
            ],
            handlers.EDIT_CATEGORIES_OTHER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_categories_other),
            ],
            handlers.EDIT_EXPERIENCE: [
                CallbackQueryHandler(handlers.edit_experience_save, pattern="^editexp_"),
            ],
            handlers.EDIT_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_description_save),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel),
            CallbackQueryHandler(handlers.show_worker_profile, pattern="^worker_profile$"),
        ],
        allow_reentry=True,
    )
    
    application.add_handler(edit_profile_handler)

    # --- ConversationHandler для добавления фото ---
    
    add_photos_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.worker_add_photos_start, pattern="^worker_add_photos$")
        ],
        states={
            handlers.ADD_PHOTOS_UPLOAD: [
                CallbackQueryHandler(handlers.worker_add_photos_upload, pattern="^finish_adding_photos$"),
                MessageHandler(filters.PHOTO | filters.TEXT, handlers.worker_add_photos_upload),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel),
            CallbackQueryHandler(handlers.show_worker_menu, pattern="^show_worker_menu$"),
        ],
        allow_reentry=True,
    )
    
    application.add_handler(add_photos_handler)

    # --- Меню мастера и заказчика ---

    application.add_handler(
        CallbackQueryHandler(
            handlers.show_worker_menu,
            pattern="^show_worker_menu$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.show_client_menu,
            pattern="^show_client_menu$",
        )
    )

    # "Мой профиль" мастера
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_worker_profile,
            pattern="^worker_profile$",
        )
    )

    # ✅ НОВОЕ: Обработчик для кнопок создания заказа и просмотра заказов
    application.add_handler(
        CallbackQueryHandler(
            handlers.client_create_order,
            pattern="^client_create_order$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.client_my_orders,
            pattern="^client_my_orders$",
        )
    )

    # Команда для очистки профиля
    application.add_handler(
        CommandHandler("reset_profile", handlers.reset_profile_command)
    )

    # Обработчик неизвестных команд
    application.add_handler(
        MessageHandler(filters.COMMAND, handlers.unknown_command)
    )

    logger.info("Бот запущен. Опрос обновлений...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
