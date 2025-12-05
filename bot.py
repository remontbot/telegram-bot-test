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
    # Инициализация connection pool (для PostgreSQL)
    db.init_connection_pool()

    db.init_db()
    db.migrate_add_portfolio_photos()  # Добавляем колонку если её нет
    db.migrate_add_order_photos()  # Добавляем колонку photos в orders
    db.migrate_add_currency_to_bids()  # Добавляем колонку currency в bids
    db.migrate_add_cascading_deletes()  # Добавляем cascading deletes для PostgreSQL
    db.migrate_add_order_completion_tracking()  # Добавляем отслеживание завершения заказов
    db.migrate_add_profile_photo()  # Добавляем поле для фото профиля мастера
    db.migrate_add_premium_features()  # Добавляем поля для premium функций (выключены по умолчанию)
    db.migrate_add_moderation()  # Добавляем поля для модерации и банов
    db.create_indexes()  # Создаем индексы для оптимизации производительности

    token = get_bot_token()

    application = ApplicationBuilder().token(token).build()

    # --- Команда /start (ОТДЕЛЬНО от ConversationHandler) ---
    application.add_handler(CommandHandler("start", handlers.start_command))

    # --- ConversationHandler для регистрации ---

    reg_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.select_role, pattern="^select_role_"),
            CallbackQueryHandler(handlers.add_second_role_worker, pattern="^role_worker$"),
            CallbackQueryHandler(handlers.add_second_role_client, pattern="^role_client$"),
        ],
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
                CallbackQueryHandler(
                    handlers.register_master_city_select,
                    pattern="^mastercity_",
                )
            ],
            handlers.REGISTER_MASTER_CITY_SELECT: [
                CallbackQueryHandler(
                    handlers.register_master_city_select,
                    pattern="^mastercity_",
                )
            ],
            handlers.REGISTER_MASTER_CITY_OTHER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_master_city_other,
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
                CallbackQueryHandler(
                    handlers.register_client_city_select,
                    pattern="^clientcity_",
                )
            ],
            handlers.REGISTER_CLIENT_CITY_SELECT: [
                CallbackQueryHandler(
                    handlers.register_client_city_select,
                    pattern="^clientcity_",
                )
            ],
            handlers.REGISTER_CLIENT_CITY_OTHER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_client_city_other,
                )
            ],
            # REGISTER_CLIENT_DESCRIPTION удалено - регистрация завершается сразу после города
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel),
        ],
        allow_reentry=True,
    )

    application.add_handler(reg_conv_handler)

    # --- ConversationHandler для создания заказа ---
    
    create_order_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.client_create_order, pattern="^client_create_order$")
        ],
        states={
            handlers.CREATE_ORDER_CITY: [
                CallbackQueryHandler(handlers.create_order_city_select, pattern="^ordercity_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.create_order_city_select),
            ],
            handlers.CREATE_ORDER_CATEGORIES: [
                CallbackQueryHandler(handlers.create_order_categories_select, pattern="^ordercat_"),
            ],
            handlers.CREATE_ORDER_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.create_order_description),
            ],
            handlers.CREATE_ORDER_PHOTOS: [
                MessageHandler(filters.PHOTO, handlers.create_order_photo_upload),
                CallbackQueryHandler(handlers.create_order_skip_photos, pattern="^order_skip_photos$"),
                CallbackQueryHandler(handlers.create_order_publish, pattern="^order_publish$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel),
        ],
        allow_reentry=True,
    )
    
    application.add_handler(create_order_handler)

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

    # --- ConversationHandler для откликов мастеров ---
    
    bid_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.worker_bid_on_order, pattern="^bid_on_order_")
        ],
        states={
            handlers.BID_ENTER_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.worker_bid_enter_price),
            ],
            handlers.BID_SELECT_CURRENCY: [
                CallbackQueryHandler(handlers.worker_bid_select_currency, pattern="^bid_currency_"),
            ],
            handlers.BID_ENTER_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.worker_bid_enter_comment),
                CallbackQueryHandler(handlers.worker_bid_skip_comment, pattern="^bid_skip_comment$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(handlers.worker_bid_cancel, pattern="^cancel_bid$"),
        ],
        allow_reentry=True,
    )
    
    application.add_handler(bid_conv_handler)

    # --- Обработчик "Мои заказы" (НЕ в ConversationHandler) ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.client_my_orders,
            pattern="^client_my_orders$",
        )
    )

    # --- Обработчики для добавления фото (БЕЗ ConversationHandler) ---
    
    # Начало добавления фото
    application.add_handler(
        CallbackQueryHandler(handlers.worker_add_photos_start, pattern="^worker_add_photos$")
    )
    
    # Завершение добавления фото
    application.add_handler(
        CallbackQueryHandler(handlers.worker_add_photos_finish_callback, pattern="^finish_adding_photos$")
    )

    # --- Обработчики фото профиля ---
    application.add_handler(
        CallbackQueryHandler(handlers.edit_profile_photo_start, pattern="^edit_profile_photo$")
    )

    application.add_handler(
        CallbackQueryHandler(handlers.cancel_profile_photo, pattern="^cancel_profile_photo$")
    )

    # Загрузка фото (обрабатывает и portfolio_photos и profile_photo)
    application.add_handler(
        MessageHandler(filters.PHOTO, handlers.worker_add_photos_upload)
    )

    # Загрузка документов (когда пользователь перетягивает файл)
    application.add_handler(
        MessageHandler(filters.Document.ALL, handlers.worker_add_photos_upload)
    )

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

    # "Доступные заказы" для мастера
    application.add_handler(
        CallbackQueryHandler(
            handlers.worker_view_orders,
            pattern="^worker_view_orders$",
        )
    )
    
    # Детальный просмотр заказа мастером
    application.add_handler(
        CallbackQueryHandler(
            handlers.worker_view_order_details,
            pattern="^view_order_"
        )
    )
    
    # Навигация по фото заказа
    application.add_handler(
        CallbackQueryHandler(
            handlers.worker_order_photo_nav,
            pattern="^order_photo_(prev|next)_"
        )
    )

    # --- Обработчики для листания мастеров ---
    
    application.add_handler(
        CallbackQueryHandler(
            handlers.go_main_menu,
            pattern="^go_main_menu$",
        )
    )
    
    application.add_handler(
        CallbackQueryHandler(
            handlers.client_browse_workers,
            pattern="^client_browse_workers$",
        )
    )
    
    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_start_viewing,
            pattern="^browse_start_now$",
        )
    )
    
    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_next_worker,
            pattern="^browse_next_worker$",
        )
    )
    
    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_photo_prev,
            pattern="^browse_photo_prev$",
        )
    )
    
    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_photo_next,
            pattern="^browse_photo_next$",
        )
    )
    
    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_restart,
            pattern="^browse_restart$",
        )
    )

    # --- Обработчики завершения заказа ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.client_complete_order,
            pattern="^complete_order_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.worker_complete_order,
            pattern="^worker_complete_order_"
        )
    )

    # --- Обработчики просмотра отзывов ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_reviews,
            pattern="^show_reviews_"
        )
    )

    # --- Обработчики галереи работ ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.view_portfolio,
            pattern="^view_portfolio$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.portfolio_navigate,
            pattern="^portfolio_(prev|next)$"
        )
    )

    # --- Обработчики просмотра откликов ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.view_order_bids,
            pattern="^view_bids_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.bid_navigate,
            pattern="^bid_(prev|next)$"
        )
    )

    # --- Обработчики выбора мастера и оплаты ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.select_master,
            pattern="^select_master_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.pay_with_stars,
            pattern="^pay_stars_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.pay_with_card,
            pattern="^pay_card_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.test_payment_success,
            pattern="^test_payment_success_"
        )
    )

    # --- ConversationHandler для отзывов ---
    review_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.start_review, pattern="^leave_review_"),
        ],
        states={
            handlers.REVIEW_SELECT_RATING: [
                CallbackQueryHandler(handlers.review_select_rating, pattern="^review_rating_"),
            ],
            handlers.REVIEW_ENTER_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.review_enter_comment),
                CallbackQueryHandler(handlers.review_skip_comment, pattern="^review_skip_comment$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(handlers.cancel_review, pattern="^cancel_review$"),
        ],
        allow_reentry=True,
    )

    application.add_handler(review_conv_handler)

    # Команда для очистки профиля
    application.add_handler(
        CommandHandler("reset_profile", handlers.reset_profile_command)
    )

    # Команда для добавления тестовых заказов
    application.add_handler(
        CommandHandler("add_test_orders", handlers.add_test_orders_command)
    )

    # Команда для добавления тестовых мастеров
    application.add_handler(
        CommandHandler("add_test_workers", handlers.add_test_workers_command)
    )

    # === ADMIN КОМАНДЫ ===

    # Команды управления premium функциями (только для администратора)
    application.add_handler(
        CommandHandler("enable_premium", handlers.enable_premium_command)
    )

    application.add_handler(
        CommandHandler("disable_premium", handlers.disable_premium_command)
    )

    application.add_handler(
        CommandHandler("premium_status", handlers.premium_status_command)
    )

    # Команды модерации (только для администратора)
    application.add_handler(
        CommandHandler("ban", handlers.ban_user_command)
    )

    application.add_handler(
        CommandHandler("unban", handlers.unban_user_command)
    )

    application.add_handler(
        CommandHandler("banned", handlers.banned_users_command)
    )

    # Команда для массовой рассылки уведомлений (только для администратора)
    application.add_handler(
        CommandHandler("announce", handlers.announce_command)
    )

    # Обработчик неизвестных команд
    application.add_handler(
        MessageHandler(filters.COMMAND, handlers.unknown_command)
    )

    logger.info("Бот запущен. Опрос обновлений...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
