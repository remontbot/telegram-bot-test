import logging
import re
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import db

logger = logging.getLogger(__name__)

(
    SELECTING_ROLE,
    REGISTER_MASTER_NAME,
    REGISTER_MASTER_PHONE,
    REGISTER_MASTER_CITY,
    REGISTER_MASTER_CATEGORIES_SELECT,
    REGISTER_MASTER_CATEGORIES_OTHER,
    REGISTER_MASTER_EXPERIENCE,
    REGISTER_MASTER_DESCRIPTION,
    REGISTER_MASTER_PHOTOS,
    REGISTER_CLIENT_NAME,
    REGISTER_CLIENT_PHONE,
    REGISTER_CLIENT_CITY,
    REGISTER_CLIENT_DESCRIPTION,
    # Новые состояния для редактирования профиля
    EDIT_PROFILE_MENU,
    EDIT_NAME,
    EDIT_PHONE,
    EDIT_CITY,
    EDIT_CATEGORIES_SELECT,
    EDIT_CATEGORIES_OTHER,
    EDIT_EXPERIENCE,
    EDIT_DESCRIPTION,
    ADD_PHOTOS_MENU,
    ADD_PHOTOS_UPLOAD,
) = range(23)


def is_valid_name(name: str) -> bool:
    if not name:
        return False
    name = name.strip()
    if len(name) < 2 or len(name) > 40:
        return False
    bad_patterns = [r"http", r"www", r"@", r"\.ru", r"\.by", r"\.com", r"t\.me"]
    return not any(re.search(p, name.lower()) for p in bad_patterns)


def is_valid_phone(phone: str) -> bool:
    phone = phone.strip()
    return bool(re.fullmatch(r"\+?\d[\d\s\-()]{6,20}", phone))


# /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_telegram_id = update.effective_user.id
    user = db.get_user(user_telegram_id)

    if user:
        user_dict = dict(user)
        role = user_dict["role"]
        user_id = user_dict["id"]
        
        # Проверяем есть ли профиль мастера
        worker_profile = db.get_worker_profile(user_id)
        # Проверяем есть ли профиль клиента
        client_profile = db.get_client_profile(user_id)
        
        has_worker = worker_profile is not None
        has_client = client_profile is not None
        
        keyboard = []
        
        if has_worker:
            keyboard.append([InlineKeyboardButton("🧰 Меню мастера", callback_data="show_worker_menu")])
        
        if has_client:
            keyboard.append([InlineKeyboardButton("🏠 Меню заказчика", callback_data="show_client_menu")])
        
        # Кнопка для создания второго профиля
        if not has_worker:
            keyboard.append([InlineKeyboardButton("➕ Стать мастером", callback_data="role_worker")])
        
        if not has_client:
            keyboard.append([InlineKeyboardButton("➕ Стать заказчиком", callback_data="role_client")])
        
        message = "👋 Добро пожаловать!\n\n"
        
        if has_worker and has_client:
            message += "У вас есть оба профиля.\nВыберите какой использовать:"
        elif has_worker:
            message += "Вы зарегистрированы как мастер.\n\nХотите также стать заказчиком?"
        elif has_client:
            message += "Вы зарегистрированы как заказчик.\n\nХотите также стать мастером?"
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        # Новый пользователь - выбор первой роли
        keyboard = [
            [InlineKeyboardButton("🧰 Я мастер (ищу заказы)", callback_data="select_role_worker")],
            [InlineKeyboardButton("🏠 Я заказчик (ищу мастера)", callback_data="select_role_client")],
        ]
        await update.message.reply_text(
            "👋 Добро пожаловать в <b>Ремонт Бот</b>.\n\n"
            "Здесь мы соединяем мастеров по ремонту и клиентов, которым нужны надёжные исполнители.\n\n"
            "Если вы мастер — бот помогает получать новые заказы.\n"
            "Если вы заказчик — вы быстро находите мастера под свою задачу.\n\n"
            "Выберите, в какой роли вы хотите продолжить:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SELECTING_ROLE


async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = query.data.split("_")[-1]
    context.user_data["selected_role"] = role

    if role == "worker":
        await query.edit_message_text(
            "🧰 Отлично! Вы регистрируетесь как <b>мастер</b>.\n\n"
            "Сейчас мы зададим несколько вопросов, чтобы клиенты могли удобно вас найти.\n"
            "Это займет 1–2 минуты.\n\n"
            "✏️ Введите ваше имя.\n"
            "Пожалуйста, без ссылок и названий компаний.\n"
            "Примеры: «Александр», «Иван Петров», «Сергей (электрик)».",
            parse_mode="HTML",
        )
        return REGISTER_MASTER_NAME
    else:
        await query.edit_message_text(
            "🏠 Отлично! Вы регистрируетесь как <b>заказчик</b>.\n\n"
            "Укажем базовые данные, чтобы мастера могли с вами связаться.\n\n"
            "✏️ Введите ваше имя.",
            parse_mode="HTML",
        )
        return REGISTER_CLIENT_NAME


# ------- РЕГИСТРАЦИЯ МАСТЕРА -------

async def register_master_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not is_valid_name(name):
        await update.message.reply_text(
            "Пожалуйста, укажите только ваше имя или имя и фамилию, без ссылок и рекламы.\n"
            "Пример: «Александр», «Иван Петров», «Сергей (мастер по электрике)»."
        )
        return REGISTER_MASTER_NAME
    context.user_data["name"] = name
    await update.message.reply_text(
        "📱 Укажите номер телефона для связи.\n"
        "Он не будет виден всем подряд — клиент получит его только после выбора вас исполнителем.\n\n"
        "Пример: +375 29 123 45 67"
    )
    return REGISTER_MASTER_PHONE


async def register_master_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not is_valid_phone(phone):
        await update.message.reply_text(
            "Не могу распознать номер.\n"
            "Пожалуйста, укажите номер в формате: +375 29 123 45 67"
        )
        return REGISTER_MASTER_PHONE
    context.user_data["phone"] = phone
    await update.message.reply_text(
        "🏙 В каком городе вы работаете?\n\n"
        "Сейчас бот в первую очередь ориентирован на Минск, но вы можете указать любой город."
    )
    return REGISTER_MASTER_CITY


async def register_master_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text.strip()
    context.user_data["city"] = city
    context.user_data["regions"] = city  # Просто сохраняем город как регион
    
    # Переходим сразу к выбору категорий
    keyboard = [
        [
            InlineKeyboardButton("Электрика", callback_data="cat_Электрика"),
            InlineKeyboardButton("Сантехника", callback_data="cat_Сантехника"),
        ],
        [
            InlineKeyboardButton("Отделка", callback_data="cat_Отделка"),
            InlineKeyboardButton("Сборка мебели", callback_data="cat_Сборка мебели"),
        ],
        [
            InlineKeyboardButton("Окна/двери", callback_data="cat_Окна/двери"),
            InlineKeyboardButton("Бытовая техника", callback_data="cat_Бытовая техника"),
        ],
        [
            InlineKeyboardButton("Напольные покрытия", callback_data="cat_Напольные покрытия"),
            InlineKeyboardButton("Мелкий ремонт", callback_data="cat_Мелкий ремонт"),
        ],
        [
            InlineKeyboardButton("Дизайн", callback_data="cat_Дизайн"),
            InlineKeyboardButton("Другое", callback_data="cat_Другое"),
        ],
        [InlineKeyboardButton("✅ Завершить выбор", callback_data="cat_done")],
    ]
    
    context.user_data["categories"] = []
    
    await update.message.reply_text(
        f"Город: {city}\n\n"
        "💡 <i>Сейчас платформа работает по всей Беларуси</i>\n\n"
        "🔧 Какие виды работ вы выполняете?\n\n"
        "Нажимайте подходящие кнопки (можно несколько).\n"
        "Если нужного варианта нет — выберите «Другое» и впишите свои.\n"
        "Когда закончите — нажмите «✅ Завершить выбор».",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return REGISTER_MASTER_CATEGORIES_SELECT


# Функция register_master_regions удалена - районы больше не используются

async def register_master_categories_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    selected = data.split("_", 1)[1]

    if selected == "done":
        if not context.user_data["categories"]:
            await query.answer("Выберите хотя бы один вид работ!", show_alert=True)
            return REGISTER_MASTER_CATEGORIES_SELECT

        keyboard = [
            [InlineKeyboardButton("Начинающий (до 1 года)", callback_data="exp_Начинающий")],
            [InlineKeyboardButton("1-3 года", callback_data="exp_1-3 года")],
            [InlineKeyboardButton("3-5 лет", callback_data="exp_3-5 лет")],
            [InlineKeyboardButton("Более 5 лет", callback_data="exp_Более 5 лет")],
        ]
        
        categories_text = ", ".join(context.user_data["categories"])
        
        await query.edit_message_text(
            f"Выбранные категории: {categories_text}\n\n"
            "📅 Укажите ваш опыт работы:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_MASTER_EXPERIENCE

    elif selected == "Другое":
        await query.edit_message_text(
            "Введите свои виды работ через запятую.\n"
            "Например: «Покраска фасадов, декорирование, гипсокартонные конструкции»"
        )
        return REGISTER_MASTER_CATEGORIES_OTHER

    else:
        if selected not in context.user_data["categories"]:
            context.user_data["categories"].append(selected)
            await query.answer(f"Добавлено: {selected}")
        else:
            context.user_data["categories"].remove(selected)
            await query.answer(f"Убрано: {selected}")

        return REGISTER_MASTER_CATEGORIES_SELECT


async def register_master_categories_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_cats = update.message.text.strip()
    custom_list = [c.strip() for c in user_cats.split(",") if c.strip()]
    context.user_data["categories"].extend(custom_list)

    keyboard = [
        [InlineKeyboardButton("Начинающий (до 1 года)", callback_data="exp_Начинающий")],
        [InlineKeyboardButton("1-3 года", callback_data="exp_1-3 года")],
        [InlineKeyboardButton("3-5 лет", callback_data="exp_3-5 лет")],
        [InlineKeyboardButton("Более 5 лет", callback_data="exp_Более 5 лет")],
    ]
    
    await update.message.reply_text(
        "Отлично 👍\n\n"
        "📅 Укажите ваш опыт работы:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return REGISTER_MASTER_EXPERIENCE


async def register_master_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    experience = query.data.replace("exp_", "")
    context.user_data["experience"] = experience
    
    await query.edit_message_text(
        f"Опыт работы: {experience}\n\n"
        "📝 Теперь расскажите немного о себе.\n\n"
        "Это описание увидят ваши потенциальные заказчики, поэтому пишите по делу:\n"
        "— стаж и специализация;\n"
        "— в чём вы сильны;\n"
        "— как работаете (аккуратность, гарантия, выезд, свой инструмент).\n\n"
        "Пример: «Опыт 6 лет. Делаю электрику в квартирах и домах, аккуратно, по нормам. "
        "Помогаю с подбором материалов. Даю гарантию на работу.»"
    )
    return REGISTER_MASTER_DESCRIPTION


async def register_master_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text.strip()
    
    # НОВОЕ: Предлагаем добавить фото работ
    keyboard = [
        [InlineKeyboardButton("📸 Да, добавить фото работ", callback_data="add_photos_yes")],
        [InlineKeyboardButton("⏭ Пропустить (добавлю позже)", callback_data="add_photos_no")],
    ]
    
    await update.message.reply_text(
        "📸 <b>Портфолио работ</b>\n\n"
        "Хотите добавить фотографии ваших работ?\n\n"
        "Фото помогут клиентам увидеть качество ваших работ и повысят доверие к вам.\n"
        "Вы сможете добавить до 10 фотографий.\n\n"
        "💡 <i>Совет: Фото работ значительно увеличивают количество откликов!</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return REGISTER_MASTER_PHOTOS


async def register_master_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора: добавлять фото или нет"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_photos_yes":
        context.user_data["portfolio_photos"] = []
        await query.edit_message_text(
            "📸 <b>Загрузка фото работ</b>\n\n"
            "Отправьте фотографии ваших работ (до 10 штук).\n"
            "Можно отправлять по одной или группой.\n\n"
            "Когда загрузите все фото, отправьте команду:\n"
            "/done_photos",
            parse_mode="HTML",
        )
        return REGISTER_MASTER_PHOTOS
    else:
        # Пропускаем фото, завершаем регистрацию
        return await finalize_master_registration(update, context)


async def handle_master_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загруженных фотографий"""
    logger.info(f"handle_master_photos вызван. Текст: {update.message.text if update.message.text else 'фото'}")
    
    # Проверяем текст сообщения
    if update.message.text:
        text = update.message.text.strip().lower()
        logger.info(f"Получен текст: '{text}'")
        
        # Проверяем различные варианты команды
        if text in ['/done_photos', 'done_photos', '/donephotos', 'donephotos', 'готово']:
            logger.info("Команда завершения фото распознана, вызываем finalize")
            return await finalize_master_registration(update, context)
    
    # Обработка фото
    if update.message.photo:
        logger.info("Получено фото")
        if "portfolio_photos" not in context.user_data:
            context.user_data["portfolio_photos"] = []
        
        photo = update.message.photo[-1]  # Берём самое большое разрешение
        file_id = photo.file_id
        
        if len(context.user_data["portfolio_photos"]) < 10:
            context.user_data["portfolio_photos"].append(file_id)
            count = len(context.user_data["portfolio_photos"])
            logger.info(f"Фото добавлено. Всего: {count}")
            await update.message.reply_text(
                f"✅ Фото {count}/10 добавлено!\n\n"
                f"Загружено фотографий: {count}\n"
                f"Можно ещё: {10 - count}\n\n"
                f"📝 Отправьте команду:\n"
                f"/done_photos\n\n"
                f"или просто напишите:\n"
                f"готово"
            )
        else:
            await update.message.reply_text(
                "⚠️ Максимум 10 фотографий.\n\n"
                "Отправьте /done_photos для завершения."
            )
        
        return REGISTER_MASTER_PHOTOS
    
    # Если пришло что-то другое
    logger.warning(f"Неожиданный ввод: {update.message.text}")
    await update.message.reply_text(
        "⚠️ Пожалуйста, отправьте:\n"
        "• Фотографии ваших работ, или\n"
        "• Команду /done_photos для завершения\n"
        "• Или напишите: готово"
    )
    return REGISTER_MASTER_PHOTOS


async def finalize_master_registration(update, context):
    """Финальное создание профиля мастера"""
    telegram_id = update.effective_user.id if update.message else update.callback_query.from_user.id
    user_id = db.create_user(telegram_id, "worker")

    # Сохраняем фото работ (если есть)
    portfolio_photos = context.user_data.get("portfolio_photos", [])
    photos_json = ",".join(portfolio_photos) if portfolio_photos else ""

    db.create_worker_profile(
        user_id=user_id,
        name=context.user_data["name"],
        phone=context.user_data["phone"],
        city=context.user_data["city"],
        regions=context.user_data["regions"],  # Теперь это просто город
        categories=", ".join(context.user_data["categories"]),
        experience=context.user_data["experience"],
        description=context.user_data["description"],
        portfolio_photos=photos_json,
    )

    keyboard = [[InlineKeyboardButton("Моё меню мастера", callback_data="show_worker_menu")]]
    
    photos_count = len(portfolio_photos)
    photos_text = f"\n📸 Добавлено фотографий: {photos_count}" if photos_count > 0 else ""
    
    message_text = (
        f"🥳 <b>Профиль мастера создан!</b>{photos_text}\n\n"
        "Теперь вы можете:\n"
        "• Посмотреть свой профиль\n"
        "• Получать заказы от клиентов\n"
        "• Добавить больше фото работ в любое время"
    )
    
    if update.message:
        await update.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
    else:
        await update.callback_query.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    context.user_data.clear()
    return ConversationHandler.END


# ------- РЕГИСТРАЦИЯ ЗАКАЗЧИКА -------

async def register_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        "📱 Какой ваш номер телефона? (например: +375 29 123 45 67)\n"
        "Он нужен, чтобы мастер смог с вами связаться."
    )
    return REGISTER_CLIENT_PHONE


async def register_client_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not is_valid_phone(phone):
        await update.message.reply_text(
            "Не могу распознать номер.\n"
            "Пожалуйста, укажите номер в формате: +375 29 123 45 67"
        )
        return REGISTER_CLIENT_PHONE

    context.user_data["phone"] = phone
    await update.message.reply_text("🏙 В каком городе вы находитесь?")
    return REGISTER_CLIENT_CITY


async def register_client_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["city"] = update.message.text.strip()
    
    # Сразу создаём профиль БЕЗ "кратко о себе"
    telegram_id = update.effective_user.id
    
    # Проверяем есть ли уже user (если добавляет вторую роль)
    existing_user = db.get_user(telegram_id)
    if existing_user:
        user_id = existing_user["id"]
    else:
        user_id = db.create_user(telegram_id, "client")

    db.create_client_profile(
        user_id=user_id,
        name=context.user_data["name"],
        phone=context.user_data["phone"],
        city=context.user_data["city"],
        description="",  # Пустое описание
    )

    keyboard = [[InlineKeyboardButton("🏠 Моё меню заказчика", callback_data="show_client_menu")]]
    await update.message.reply_text(
        "🥳 <b>Профиль заказчика создан!</b>\n\n"
        "Теперь вы можете:\n"
        "• 🔍 Искать мастеров\n"
        "• 📝 Создавать заказы\n"
        "• 💬 Общаться с мастерами\n\n"
        "Детали о задаче вы опишете при создании заказа!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    context.user_data.clear()
    return ConversationHandler.END

    context.user_data.clear()
    return ConversationHandler.END


# ------- МЕНЮ -------

async def show_worker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👤 Мой профиль", callback_data="worker_profile")],
        # [InlineKeyboardButton("📸 Добавить фото работ", callback_data="worker_add_photos")],  # Временно отключено
        # сюда позже: "Доступные заказы", "Мои отклики"
        [InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")],
    ]
    await query.edit_message_text(
        "🧰 Меню мастера.\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔍 Найти мастера", callback_data="client_browse_workers")],
        [InlineKeyboardButton("📝 Создать заказ", callback_data="client_create_order")],
        [InlineKeyboardButton("📂 Мои заказы", callback_data="client_my_orders")],
        [InlineKeyboardButton("🧰 Главное меню", callback_data="go_main_menu")],
    ]
    await query.edit_message_text(
        "🏠 Меню заказчика.\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ------- ПРОФИЛЬ МАСТЕРА -------

async def show_worker_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ профиля мастера с правильным доступом к базе данных"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    logger.info(f"Запрос профиля мастера для telegram_id: {telegram_id}")
    
    try:
        user = db.get_user(telegram_id)
        
        if not user:
            logger.error(f"Пользователь не найден: telegram_id={telegram_id}")
            await query.edit_message_text(
                "❌ Профиль не найден в базе данных.\n\n"
                "Попробуйте использовать /reset_profile и зарегистрируйтесь заново."
            )
            return

        # ИСПРАВЛЕНО: Используем dict() для безопасного доступа к sqlite3.Row
        user_dict = dict(user)
        user_id = user_dict.get("id")
        role = user_dict.get("role")
        
        logger.info(f"Найден пользователь: id={user_id}, role={role}")
        
        if role != "worker":
            logger.error(f"Пользователь не является мастером: role={role}")
            await query.edit_message_text(
                "❌ Вы не зарегистрированы как мастер.\n\n"
                "Используйте /reset_profile для перерегистрации."
            )
            return

        worker_profile = db.get_worker_profile(user_id)

        if not worker_profile:
            logger.error(f"Профиль мастера не найден для user_id={user_id}")
            await query.edit_message_text(
                "❌ Профиль мастера не заполнен.\n\n"
                "Используйте /reset_profile и пройдите регистрацию заново."
            )
            return

        logger.info(f"Профиль мастера найден для user_id={user_id}")

        # ИСПРАВЛЕНО: Конвертируем в dict для безопасного доступа к sqlite3.Row
        profile_dict = dict(worker_profile)
        
        name = profile_dict.get("name") or "—"
        phone = profile_dict.get("phone") or "—"
        city = profile_dict.get("city") or "—"
        regions = profile_dict.get("regions") or "—"
        categories = profile_dict.get("categories") or "—"
        experience = profile_dict.get("experience") or "—"
        description = profile_dict.get("description") or "—"
        rating = profile_dict.get("rating") or 0
        rating_count = profile_dict.get("rating_count") or 0
        verified_reviews = profile_dict.get("verified_reviews") or 0
        portfolio_photos = profile_dict.get("portfolio_photos") or ""
        
        # Подсчёт фотографий
        photos_count = len(portfolio_photos.split(",")) if portfolio_photos else 0
        
        if rating and rating > 0:
            rating_text = f"⭐ {rating:.1f}/5.0"
            reviews_text = f"📊 Отзывов: {rating_count} (проверенных: {verified_reviews})"
        else:
            rating_text = "⭐ Нет отзывов"
            reviews_text = "📊 Отзывов пока нет"
        
        photos_text = f"📸 Фото работ: {photos_count}" if photos_count > 0 else "📸 Фото работ: не добавлено"

        text = (
            "👤 <b>Ваш профиль мастера</b>\n\n"
            f"<b>Имя:</b> {name}\n"
            f"<b>Телефон:</b> {phone}\n"
            f"<b>Город:</b> {city}\n"
            f"<b>Районы:</b> {regions}\n"
            f"<b>Виды работ:</b> {categories}\n"
            f"<b>Опыт:</b> {experience}\n\n"
            f"<b>Описание:</b>\n{description}\n\n"
            f"{rating_text}\n"
            f"{reviews_text}\n"
            f"{photos_text}"
        )

        keyboard = [
            [InlineKeyboardButton("✏️ Редактировать профиль", callback_data="edit_profile_menu")],
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")],
        ]
        
        # Если есть фото - показываем первое
        if portfolio_photos:
            first_photo = portfolio_photos.split(",")[0]
            await query.message.reply_photo(
                photo=first_photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            await query.message.delete()
        else:
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        
        logger.info(f"Профиль успешно отображён для telegram_id={telegram_id}")

    except Exception as e:
        logger.error(f"Ошибка при отображении профиля: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка при загрузке профиля.\n\n"
            f"Детали: {str(e)}\n\n"
            f"Используйте /reset_profile для сброса профиля."
        )


# ------- ДОБАВЛЕНИЕ ФОТО ПОСЛЕ РЕГИСТРАЦИИ (БЕЗ ConversationHandler) -------

async def worker_add_photos_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления фото работ"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_photos = profile_dict.get("portfolio_photos") or ""
    
    # Подсчитываем текущие фото
    current_photos_list = [p for p in current_photos.split(",") if p] if current_photos else []
    current_count = len(current_photos_list)
    max_photos = 10
    available_slots = max_photos - current_count
    
    # Сохраняем в context - РЕЖИМ ДОБАВЛЕНИЯ ФОТО АКТИВЕН
    context.user_data["adding_photos"] = True
    context.user_data["existing_photos"] = current_photos_list
    context.user_data["new_photos"] = []
    
    logger.info(f"Запущен режим добавления фото для user_id={user_id}")
    
    if available_slots <= 0:
        await query.edit_message_text(
            "📸 <b>Портфолио заполнено</b>\n\n"
            f"У вас уже загружено максимальное количество фото ({max_photos}).\n\n"
            "Чтобы добавить новые фото, сначала нужно удалить старые.\n"
            "(Функция удаления будет добавлена в следующем обновлении)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
            ])
        )
        context.user_data.clear()
        return
    
    status_text = f"📊 Текущее состояние:\n" \
                  f"• Загружено фото: {current_count}/{max_photos}\n" \
                  f"• Можно добавить ещё: {available_slots}"
    
    await query.edit_message_text(
        f"📸 <b>Добавление фото работ</b>\n\n"
        f"{status_text}\n\n"
        f"Отправьте новые фотографии ваших работ (можно до {available_slots} штук).\n"
        f"Можно отправлять по одной или группой.\n\n"
        f"Когда загрузите все фото, нажмите кнопку ниже:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]
        ])
    )


async def worker_add_photos_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загружаемых фото"""
    
    # Проверяем активен ли режим добавления фото
    if not context.user_data.get("adding_photos"):
        # Игнорируем фото если режим не активен
        logger.info("Получено фото но режим добавления не активен - игнорируем")
        return
    
    # Обработка фото
    if update.message and update.message.photo:
        logger.info("Получено фото для добавления в портфолио")
        existing_count = len(context.user_data.get("existing_photos", []))
        new_count = len(context.user_data.get("new_photos", []))
        total_count = existing_count + new_count
        max_photos = 10
        
        if total_count >= max_photos:
            keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
            await update.message.reply_text(
                f"⚠️ Достигнут лимит в {max_photos} фотографий.\n\n"
                f"Нажмите кнопку ниже для завершения:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            return
        
        photo = update.message.photo[-1]  # Берём самое большое разрешение
        file_id = photo.file_id
        
        context.user_data["new_photos"].append(file_id)
        new_count = len(context.user_data["new_photos"])
        total_count = existing_count + new_count
        remaining = max_photos - total_count
        
        logger.info(f"Фото добавлено. Новых: {new_count}, Всего: {total_count}")
        
        # ДОБАВЛЯЕМ КНОПКУ для завершения
        keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
        
        await update.message.reply_text(
            f"✅ Фото добавлено!\n\n"
            f"📊 Статус:\n"
            f"• Было фото: {existing_count}\n"
            f"• Добавлено новых: {new_count}\n"
            f"• Всего будет: {total_count}/{max_photos}\n"
            f"• Можно ещё: {remaining}\n\n"
            f"Отправьте ещё фото или нажмите кнопку:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )


async def worker_add_photos_finish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки завершения"""
    query = update.callback_query
    await query.answer()
    
    logger.info("Нажата кнопка завершения добавления фото")
    
    # Проверяем активен ли режим
    if not context.user_data.get("adding_photos"):
        logger.warning("Режим добавления фото не активен!")
        await query.edit_message_text(
            "⚠️ Режим добавления фото не активен.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
            ])
        )
        return
    
    # Вызываем функцию завершения
    await worker_add_photos_finish(query, context)


async def worker_add_photos_finish(query, context: ContextTypes.DEFAULT_TYPE):
    """Завершение добавления фото - сохранение в БД"""
    
    logger.info("=== worker_add_photos_finish вызвана ===")
    
    new_photos = context.user_data.get("new_photos", [])
    existing_photos = context.user_data.get("existing_photos", [])
    
    logger.info(f"new_photos count: {len(new_photos)}")
    logger.info(f"existing_photos count: {len(existing_photos)}")
    
    if not new_photos:
        logger.warning("Нет новых фото для сохранения")
        keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]]
        
        # Удаляем старое сообщение и отправляем новое
        try:
            await query.message.delete()
        except:
            pass
        
        await query.message.reply_text(
            "⚠️ Вы не добавили ни одного фото.\n\nОперация отменена.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        context.user_data.clear()
        logger.info("Context очищен")
        return
    
    try:
        # Объединяем старые и новые фото
        all_photos = existing_photos + new_photos
        photos_string = ",".join(all_photos)
        
        logger.info(f"Объединённые фото (всего {len(all_photos)})")
        
        # Получаем telegram_id
        telegram_id = query.from_user.id
        logger.info(f"telegram_id: {telegram_id}")
        
        # Получаем user из БД
        user = db.get_user(telegram_id)
        if not user:
            logger.error(f"Пользователь не найден в БД: telegram_id={telegram_id}")
            raise ValueError(f"User not found: {telegram_id}")
        
        user_dict = dict(user)
        user_id = user_dict.get("id")
        logger.info(f"user_id из БД: {user_id}")
        
        # Обновляем в БД
        result = db.update_worker_field(user_id, "portfolio_photos", photos_string)
        logger.info(f"Результат обновления БД: {result}")
        
        keyboard = [[InlineKeyboardButton("👤 Мой профиль", callback_data="worker_profile")],
                    [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]]
        
        added_count = len(new_photos)
        total_count = len(all_photos)
        
        message_text = (
            f"✅ <b>Фото успешно добавлены!</b>\n\n"
            f"📊 Итого:\n"
            f"• Добавлено новых: {added_count}\n"
            f"• Всего в портфолио: {total_count}/10\n\n"
            f"Теперь клиенты увидят ваши работы!"
        )
        
        logger.info("Отправка успешного сообщения пользователю")
        
        # ВАЖНО: Удаляем старое сообщение и отправляем НОВОЕ
        # Потому что последнее сообщение может быть фото (которое нельзя редактировать на текст)
        try:
            await query.message.delete()
        except:
            pass  # Если не получилось удалить - не страшно
        
        # Отправляем НОВОЕ сообщение с результатом
        await query.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        
        logger.info("Фото успешно сохранены, ОЧИЩАЮ context.user_data")
        # ВАЖНО: Очищаем context чтобы выйти из режима добавления фото
        context.user_data.clear()
        logger.info("Context очищен - режим добавления фото завершён")
        
    except Exception as e:
        logger.error(f"Ошибка в worker_add_photos_finish: {e}", exc_info=True)
        
        error_text = (
            f"❌ Произошла ошибка при сохранении фото.\n\n"
            f"Детали: {str(e)}\n\n"
            f"Попробуйте ещё раз или обратитесь в поддержку."
        )
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]]
        
        # Удаляем старое и отправляем новое
        try:
            await query.message.delete()
        except:
            pass
        
        await query.message.reply_text(
            error_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        context.user_data.clear()
        logger.info("Context очищен после ошибки")
        
        context.user_data.clear()
        return ConversationHandler.END


# ------- РЕДАКТИРОВАНИЕ ПРОФИЛЯ -------

async def show_edit_profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню редактирования профиля"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("✏️ Изменить имя", callback_data="edit_name")],
        [InlineKeyboardButton("📱 Изменить телефон", callback_data="edit_phone")],
        [InlineKeyboardButton("🏙 Изменить город", callback_data="edit_city")],
        [InlineKeyboardButton("🔧 Изменить виды работ", callback_data="edit_categories")],
        [InlineKeyboardButton("📅 Изменить опыт", callback_data="edit_experience")],
        [InlineKeyboardButton("📝 Изменить описание", callback_data="edit_description")],
        [InlineKeyboardButton("⬅️ Назад к профилю", callback_data="worker_profile")],
    ]
    
    await query.edit_message_text(
        "✏️ <b>Редактирование профиля</b>\n\n"
        "Выберите что хотите изменить:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return EDIT_PROFILE_MENU


async def edit_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования имени"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_name = profile_dict.get("name") or "—"
    
    await query.edit_message_text(
        f"✏️ <b>Изменение имени</b>\n\n"
        f"Текущее имя: <b>{current_name}</b>\n\n"
        f"Введите новое имя:\n"
        f"Например: «Александр», «Иван Петров»\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_NAME


async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового имени"""
    new_name = update.message.text.strip()
    
    if not is_valid_name(new_name):
        await update.message.reply_text(
            "❌ Неверный формат имени.\n"
            "Укажите только имя или имя и фамилию, без ссылок.\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_NAME
    
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "name", new_name)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await update.message.reply_text(
        f"✅ Имя успешно изменено на: <b>{new_name}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_phone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования телефона"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_phone = profile_dict.get("phone") or "—"
    
    await query.edit_message_text(
        f"📱 <b>Изменение телефона</b>\n\n"
        f"Текущий телефон: <b>{current_phone}</b>\n\n"
        f"Введите новый номер телефона:\n"
        f"Пример: +375 29 123 45 67\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_PHONE


async def edit_phone_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового телефона"""
    new_phone = update.message.text.strip()
    
    if not is_valid_phone(new_phone):
        await update.message.reply_text(
            "❌ Неверный формат телефона.\n"
            "Пример: +375 29 123 45 67\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_PHONE
    
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "phone", new_phone)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await update.message.reply_text(
        f"✅ Телефон успешно изменён на: <b>{new_phone}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_city_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования города"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_city = profile_dict.get("city") or "—"
    
    await query.edit_message_text(
        f"🏙 <b>Изменение города</b>\n\n"
        f"Текущий город: <b>{current_city}</b>\n\n"
        f"Введите новый город:\n"
        f"Например: Минск, Гомель, Брест\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_CITY


async def edit_city_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового города"""
    new_city = update.message.text.strip()
    
    if len(new_city) < 2:
        await update.message.reply_text(
            "❌ Слишком короткое название города.\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_CITY
    
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "city", new_city)
    db.update_worker_field(user_id, "regions", new_city)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await update.message.reply_text(
        f"✅ Город успешно изменён на: <b>{new_city}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_categories_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования категорий"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_categories = profile_dict.get("categories") or "—"
    
    context.user_data["edit_categories"] = []
    
    keyboard = [
        [
            InlineKeyboardButton("Электрика", callback_data="editcat_Электрика"),
            InlineKeyboardButton("Сантехника", callback_data="editcat_Сантехника"),
        ],
        [
            InlineKeyboardButton("Отделка", callback_data="editcat_Отделка"),
            InlineKeyboardButton("Сборка мебели", callback_data="editcat_Сборка мебели"),
        ],
        [
            InlineKeyboardButton("Окна/двери", callback_data="editcat_Окна/двери"),
            InlineKeyboardButton("Бытовая техника", callback_data="editcat_Бытовая техника"),
        ],
        [
            InlineKeyboardButton("Напольные покрытия", callback_data="editcat_Напольные покрытия"),
            InlineKeyboardButton("Мелкий ремонт", callback_data="editcat_Мелкий ремонт"),
        ],
        [
            InlineKeyboardButton("Дизайн", callback_data="editcat_Дизайн"),
            InlineKeyboardButton("Другое", callback_data="editcat_Другое"),
        ],
        [InlineKeyboardButton("✅ Сохранить выбор", callback_data="editcat_done")],
        [InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")],
    ]
    
    await query.edit_message_text(
        f"🔧 <b>Изменение видов работ</b>\n\n"
        f"Текущие категории:\n<b>{current_categories}</b>\n\n"
        f"Выберите новые категории (можно несколько):\n"
        f"Нажимайте на кнопки для добавления/удаления.\n"
        f"Когда закончите — нажмите «✅ Сохранить выбор»",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return EDIT_CATEGORIES_SELECT


async def edit_categories_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора категорий"""
    query = update.callback_query
    await query.answer()
    data = query.data
    selected = data.split("_", 1)[1]
    
    if selected == "done":
        if not context.user_data["edit_categories"]:
            await query.answer("❌ Выберите хотя бы одну категорию!", show_alert=True)
            return EDIT_CATEGORIES_SELECT
        
        telegram_id = query.from_user.id
        user = db.get_user(telegram_id)
        user_dict = dict(user)
        user_id = user_dict.get("id")
        
        new_categories = ", ".join(context.user_data["edit_categories"])
        db.update_worker_field(user_id, "categories", new_categories)
        
        context.user_data.clear()
        
        keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
        
        await query.edit_message_text(
            f"✅ Виды работ успешно изменены на:\n<b>{new_categories}</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return ConversationHandler.END
    
    elif selected == "Другое":
        await query.edit_message_text(
            "Введите свои виды работ через запятую.\n"
            "Например: «Покраска фасадов, декорирование»\n\n"
            "Или /cancel для отмены"
        )
        return EDIT_CATEGORIES_OTHER
    
    else:
        if selected not in context.user_data["edit_categories"]:
            context.user_data["edit_categories"].append(selected)
            await query.answer(f"✅ Добавлено: {selected}")
        else:
            context.user_data["edit_categories"].remove(selected)
            await query.answer(f"❌ Убрано: {selected}")
        
        return EDIT_CATEGORIES_SELECT


async def edit_categories_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кастомных категорий"""
    user_cats = update.message.text.strip()
    custom_list = [c.strip() for c in user_cats.split(",") if c.strip()]
    context.user_data["edit_categories"].extend(custom_list)
    
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    new_categories = ", ".join(context.user_data["edit_categories"])
    db.update_worker_field(user_id, "categories", new_categories)
    
    context.user_data.clear()
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await update.message.reply_text(
        f"✅ Виды работ успешно изменены на:\n<b>{new_categories}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_experience_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования опыта"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_exp = profile_dict.get("experience") or "—"
    
    keyboard = [
        [InlineKeyboardButton("Начинающий (до 1 года)", callback_data="editexp_Начинающий")],
        [InlineKeyboardButton("1-3 года", callback_data="editexp_1-3 года")],
        [InlineKeyboardButton("3-5 лет", callback_data="editexp_3-5 лет")],
        [InlineKeyboardButton("Более 5 лет", callback_data="editexp_Более 5 лет")],
        [InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")],
    ]
    
    await query.edit_message_text(
        f"📅 <b>Изменение опыта работы</b>\n\n"
        f"Текущий опыт: <b>{current_exp}</b>\n\n"
        f"Выберите новый опыт:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return EDIT_EXPERIENCE


async def edit_experience_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового опыта"""
    query = update.callback_query
    await query.answer()
    
    new_exp = query.data.replace("editexp_", "")
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "experience", new_exp)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await query.edit_message_text(
        f"✅ Опыт работы успешно изменён на: <b>{new_exp}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_description_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования описания"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_desc = profile_dict.get("description") or "—"
    
    await query.edit_message_text(
        f"📝 <b>Изменение описания</b>\n\n"
        f"Текущее описание:\n<i>{current_desc}</i>\n\n"
        f"Введите новое описание профиля:\n"
        f"Расскажите о своём опыте, специализации, как работаете.\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_DESCRIPTION


async def edit_description_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового описания"""
    new_desc = update.message.text.strip()
    
    if len(new_desc) < 10:
        await update.message.reply_text(
            "❌ Описание слишком короткое (минимум 10 символов).\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_DESCRIPTION
    
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "description", new_desc)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await update.message.reply_text(
        f"✅ Описание успешно изменено!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ------- ЗАГЛУШКИ ДЛЯ ЗАКАЗЧИКА -------

async def client_create_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание заказа (пока заглушка)"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📝 <b>Создание заказа</b>\n\n"
        "Эта функция в разработке.\n\n"
        "Скоро здесь вы сможете:\n"
        "• Описать задачу\n"
        "• Указать бюджет и сроки\n"
        "• Получить отклики от мастеров",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")]
        ])
    )


async def client_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр заказов (пока заглушка)"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📂 <b>Мои заказы</b>\n\n"
        "У вас пока нет созданных заказов.\n\n"
        "Создайте первый заказ, чтобы начать получать отклики от мастеров!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")]
        ])
    )


# ------- СЛУЖЕБНЫЕ -------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Команда не распознана. Используйте /start.")


async def handle_invalid_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Не вижу тут ожидаемого ответа. Попробуйте ещё раз или введите /start."
        )
    elif update.callback_query:
        await update.callback_query.answer("Неверное действие. Используйте /start для начала.")


async def reset_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для полной очистки профиля пользователя из базы данных"""
    telegram_id = update.effective_user.id
    
    success = db.delete_user_profile(telegram_id)
    
    if success:
        await update.message.reply_text(
            "✅ Ваш профиль успешно удалён из базы данных.\n\n"
            "Теперь вы можете зарегистрироваться заново, используя команду /start"
        )
    else:
        await update.message.reply_text(
            "⚠️ Профиль не найден или уже удалён.\n\n"
            "Используйте /start для регистрации."
        )
# ------- ЛИСТАНИЕ МАСТЕРОВ ДЛЯ КЛИЕНТОВ -------

async def client_browse_workers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало просмотра мастеров - выбор фильтров"""
    query = update.callback_query
    await query.answer()
    
    # Сбрасываем фильтры
    context.user_data.pop("browse_city", None)
    context.user_data.pop("browse_category", None)
    
    keyboard = [
        [InlineKeyboardButton("▶️ Начать просмотр", callback_data="browse_start_now")],
        [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")],
    ]
    
    await query.edit_message_text(
        "🔍 <b>Поиск мастера</b>\n\n"
        "Сейчас показываем всех мастеров.\n\n"
        "(Фильтры по городу и категориям добавим в следующей версии)\n\n"
        "Нажмите \"Начать просмотр\" чтобы увидеть карточки мастеров:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def browse_start_viewing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало просмотра карточек мастеров"""
    query = update.callback_query
    await query.answer()
    
    # Получаем фильтры из context (если есть)
    city_filter = context.user_data.get("browse_city")
    category_filter = context.user_data.get("browse_category")
    
    # Получаем список мастеров
    workers = db.get_all_workers(city=city_filter, category=category_filter)
    
    if not workers:
        await query.edit_message_text(
            "😔 <b>Мастера не найдены</b>\n\n"
            "Пока ни один мастер не зарегистрировался.\n"
            "Попробуйте зайти позже!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")],
            ])
        )
        return
    
    # Сохраняем список и индекс текущего мастера
    context.user_data["workers_list"] = [dict(w) for w in workers]
    context.user_data["current_worker_index"] = 0
    context.user_data["current_photo_index"] = 0
    
    logger.info(f"Найдено мастеров: {len(workers)}")
    
    # Показываем первого мастера
    await show_worker_card(query, context, edit=True)


async def show_worker_card(query_or_message, context: ContextTypes.DEFAULT_TYPE, edit=False):
    """Показывает карточку мастера"""
    
    workers_list = context.user_data.get("workers_list", [])
    worker_index = context.user_data.get("current_worker_index", 0)
    photo_index = context.user_data.get("current_photo_index", 0)
    
    if worker_index >= len(workers_list):
        # Все мастера просмотрены
        keyboard = [
            [InlineKeyboardButton("🔄 Начать сначала", callback_data="browse_restart")],
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")],
        ]
        
        text = (
            "✅ <b>Вы просмотрели всех мастеров!</b>\n\n"
            "Можете начать сначала или вернуться в меню."
        )
        
        if hasattr(query_or_message, 'edit_message_text'):
            await query_or_message.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query_or_message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return
    
    worker = workers_list[worker_index]
    
    # Формируем текст карточки
    name = worker.get("name", "Без имени")
    city = worker.get("city", "Не указан")
    categories = worker.get("categories", "Не указаны")
    experience = worker.get("experience", "Не указан")
    description = worker.get("description", "Нет описания")
    rating = worker.get("rating", 0.0)
    rating_count = worker.get("rating_count", 0)
    portfolio_photos = worker.get("portfolio_photos", "")
    
    # Обрабатываем фото
    photos_list = [p for p in portfolio_photos.split(",") if p] if portfolio_photos else []
    
    card_text = f"👤 <b>{name}</b>\n\n"
    card_text += f"📍 Город: {city}\n"
    card_text += f"🔧 Категории: {categories}\n"
    card_text += f"💼 Опыт: {experience}\n"
    card_text += f"⭐ Рейтинг: {rating:.1f} ({rating_count} отзывов)\n\n"
    card_text += f"📝 {description}\n\n"
    
    if photos_list:
        card_text += f"📸 Фото работ: {photo_index + 1}/{len(photos_list)}"
    else:
        card_text += "📸 Нет фото работ"
    
    # Кнопки навигации
    keyboard = []
    
    # Навигация по фото
    if photos_list and len(photos_list) > 1:
        photo_nav = []
        if photo_index > 0:
            photo_nav.append(InlineKeyboardButton("⬅️ Фото", callback_data="browse_photo_prev"))
        if photo_index < len(photos_list) - 1:
            photo_nav.append(InlineKeyboardButton("Фото ➡️", callback_data="browse_photo_next"))
        
        if photo_nav:
            keyboard.append(photo_nav)
    
    # Действия с мастером
    keyboard.append([
        InlineKeyboardButton("💬 Написать", url=f"tg://user?id={worker.get('telegram_id')}")
    ])
    
    # Навигация по мастерам
    nav_buttons = []
    if worker_index < len(workers_list) - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ Следующий мастер", callback_data="browse_next_worker"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")])
    
    # Отправляем карточку
    if photos_list:
        # Отправляем фото
        current_photo = photos_list[photo_index]
        
        if edit and hasattr(query_or_message, 'message'):
            # Удаляем старое сообщение и отправляем новое с фото
            try:
                await query_or_message.message.delete()
            except:
                pass
            
            await query_or_message.message.reply_photo(
                photo=current_photo,
                caption=card_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Просто отправляем фото
            await query_or_message.reply_photo(
                photo=current_photo,
                caption=card_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        # Нет фото - отправляем только текст
        if edit and hasattr(query_or_message, 'edit_message_text'):
            await query_or_message.edit_message_text(
                card_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query_or_message.reply_text(
                card_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )


async def browse_next_worker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение на следующего мастера"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["current_worker_index"] = context.user_data.get("current_worker_index", 0) + 1
    context.user_data["current_photo_index"] = 0  # Сбрасываем индекс фото
    
    await show_worker_card(query, context, edit=True)


async def browse_photo_prev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Предыдущее фото мастера"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["current_photo_index"] = max(0, context.user_data.get("current_photo_index", 0) - 1)
    
    await show_worker_card(query, context, edit=True)


async def browse_photo_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Следующее фото мастера"""
    query = update.callback_query
    await query.answer()
    
    workers_list = context.user_data.get("workers_list", [])
    worker_index = context.user_data.get("current_worker_index", 0)
    
    if worker_index < len(workers_list):
        worker = workers_list[worker_index]
        photos_list = [p for p in worker.get("portfolio_photos", "").split(",") if p]
        
        current_photo_index = context.user_data.get("current_photo_index", 0)
        context.user_data["current_photo_index"] = min(len(photos_list) - 1, current_photo_index + 1)
    
    await show_worker_card(query, context, edit=True)


async def browse_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать просмотр мастеров сначала"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["current_worker_index"] = 0
    context.user_data["current_photo_index"] = 0
    
    await show_worker_card(query, context, edit=True)


# ------- ПЕРЕКЛЮЧЕНИЕ МЕЖДУ РОЛЯМИ -------

async def go_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню с выбором роли"""
    query = update.callback_query
    await query.answer()
    
    user_telegram_id = query.from_user.id
    user = db.get_user(user_telegram_id)
    
    if not user:
        await query.edit_message_text("Ошибка: пользователь не найден")
        return
    
    user_dict = dict(user)
    user_id = user_dict["id"]
    
    # Проверяем есть ли профиль мастера
    worker_profile = db.get_worker_profile(user_id)
    # Проверяем есть ли профиль клиента
    client_profile = db.get_client_profile(user_id)
    
    has_worker = worker_profile is not None
    has_client = client_profile is not None
    
    keyboard = []
    
    if has_worker:
        keyboard.append([InlineKeyboardButton("🧰 Меню мастера", callback_data="show_worker_menu")])
    
    if has_client:
        keyboard.append([InlineKeyboardButton("🏠 Меню заказчика", callback_data="show_client_menu")])
    
    # Кнопка для создания второго профиля
    if not has_worker:
        keyboard.append([InlineKeyboardButton("➕ Стать мастером", callback_data="role_worker")])
    
    if not has_client:
        keyboard.append([InlineKeyboardButton("➕ Стать заказчиком", callback_data="role_client")])
    
    message = "🏠 <b>Главное меню</b>\n\n"
    
    if has_worker and has_client:
        message += "У вас есть оба профиля.\nВыберите какой использовать:"
    elif has_worker:
        message += "Вы зарегистрированы как мастер.\n\nХотите также стать заказчиком?"
    elif has_client:
        message += "Вы зарегистрированы как заказчик.\n\nХотите также стать мастером?"
    
    await query.edit_message_text(
        message,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def add_second_role_worker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление роли мастера к существующему аккаунту"""
    query = update.callback_query
    await query.answer()
    
    # Запускаем регистрацию мастера
    await query.edit_message_text(
        "🧰 <b>Регистрация мастера</b>\n\n"
        "Как вас зовут? Введите ваше имя:",
        parse_mode="HTML"
    )
    
    # Переходим в состояние ввода имени мастера
    return REGISTER_MASTER_NAME


async def add_second_role_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление роли заказчика к существующему аккаунту"""
    query = update.callback_query
    await query.answer()
    
    # Запускаем регистрацию заказчика
    await query.edit_message_text(
        "🏠 <b>Регистрация заказчика</b>\n\n"
        "Как вас зовут? Введите ваше имя:",
        parse_mode="HTML"
    )
    
    # Переходим в состояние ввода имени клиента
    return REGISTER_CLIENT_NAME
