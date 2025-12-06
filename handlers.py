import logging
import re
import asyncio
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


# ===== HELPER FUNCTIONS =====

def _get_bids_word(count):
    """Возвращает правильное склонение слова 'отклик'"""
    if count % 10 == 1 and count % 100 != 11:
        return "отклик"
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "отклика"
    else:
        return "откликов"

(
    SELECTING_ROLE,
    REGISTER_MASTER_NAME,
    REGISTER_MASTER_PHONE,
    REGISTER_MASTER_CITY,
    REGISTER_MASTER_CITY_SELECT,
    REGISTER_MASTER_CITY_OTHER,
    REGISTER_MASTER_CATEGORIES_SELECT,
    REGISTER_MASTER_CATEGORIES_OTHER,
    REGISTER_MASTER_EXPERIENCE,
    REGISTER_MASTER_DESCRIPTION,
    REGISTER_MASTER_PHOTOS,
    REGISTER_CLIENT_NAME,
    REGISTER_CLIENT_PHONE,
    REGISTER_CLIENT_CITY,
    REGISTER_CLIENT_CITY_SELECT,
    REGISTER_CLIENT_CITY_OTHER,
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
    # Состояния для создания заказа
    CREATE_ORDER_CITY,
    CREATE_ORDER_CATEGORIES,
    CREATE_ORDER_DESCRIPTION,
    CREATE_ORDER_PHOTOS,
    # Состояния для создания отклика
    BID_ENTER_PRICE,
    BID_SELECT_CURRENCY,
    BID_ENTER_COMMENT,
    # Состояния для оставления отзыва
    REVIEW_SELECT_RATING,
    REVIEW_ENTER_COMMENT,
) = range(36)


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

    # Проверяем не забанен ли пользователь
    if db.is_user_banned(user_telegram_id):
        await update.message.reply_text(
            "🚫 <b>Доступ заблокирован</b>\n\n"
            "Ваш аккаунт заблокирован администратором.\n\n"
            "Если вы считаете, что это ошибка, обратитесь в поддержку.",
            parse_mode="HTML"
        )
        return

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
    
    # Предлагаем выбор города из Беларуси
    cities = [
        "Минск", "Гомель", "Могилёв", "Витебск",
        "Гродно", "Брест", "Бобруйск", "Барановичи",
        "Борисов", "Пинск", "Орша", "Мозырь",
        "Новополоцк", "Лида", "Солигорск",
        "Вся Беларусь", "Другой город"
    ]
    
    keyboard = []
    row = []
    for i, city in enumerate(cities):
        row.append(InlineKeyboardButton(city, callback_data=f"mastercity_{city}"))
        if len(row) == 2 or i == len(cities) - 1:
            keyboard.append(row)
            row = []
    
    await update.message.reply_text(
        "🏙 <b>Где вы работаете?</b>\n\n"
        "Можете выбрать \"Вся Беларусь\" если работаете по всей стране.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REGISTER_MASTER_CITY_SELECT


async def register_master_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города мастером"""
    query = update.callback_query
    await query.answer()
    
    city = query.data.replace("mastercity_", "")
    
    if city == "Другой город":
        await query.edit_message_text(
            "🏙 Напишите где вы работаете:"
        )
        return REGISTER_MASTER_CITY_OTHER
    else:
        context.user_data["city"] = city
        context.user_data["regions"] = city
        
        # Переходим к выбору категорий
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
        
        await query.edit_message_text(
            f"Город: {city}\n\n"
            "🔧 Какие виды работ вы выполняете?\n\n"
            "Нажимайте подходящие кнопки (можно несколько).\n"
            "Если нужного варианта нет — выберите «Другое» и впишите свои.\n"
            "Когда закончите — нажмите «✅ Завершить выбор».",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_MASTER_CATEGORIES_SELECT


async def register_master_city_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод другого города мастером"""
    city = update.message.text.strip()
    context.user_data["city"] = city
    context.user_data["regions"] = city
    
    # Переходим к выбору категорий
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
        "🔧 Какие виды работ вы выполняете?\n\n"
        "Нажимайте подходящие кнопки (можно несколько).\n"
        "Если нужного варианта нет — выберите «Другое» и впишите свои.\n"
        "Когда закончите — нажмите «✅ Завершить выбор».",
        reply_markup=InlineKeyboardMarkup(keyboard),
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
    
    # Предлагаем выбор города из Беларуси
    cities = [
        "Минск", "Гомель", "Могилёв", "Витебск",
        "Гродно", "Брест", "Бобруйск", "Барановичи",
        "Борисов", "Пинск", "Орша", "Мозырь",
        "Новополоцк", "Лида", "Солигорск",
        "Вся Беларусь", "Другой город"
    ]
    
    keyboard = []
    row = []
    for i, city in enumerate(cities):
        row.append(InlineKeyboardButton(city, callback_data=f"clientcity_{city}"))
        if len(row) == 2 or i == len(cities) - 1:
            keyboard.append(row)
            row = []
    
    await update.message.reply_text(
        "🏙 <b>Выберите ваш город:</b>\n\n"
        "Можете выбрать \"Вся Беларусь\" если работаете по всей стране.\n"
        "Если вашего города нет - нажмите \"Другой город\"",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REGISTER_CLIENT_CITY_SELECT


async def register_client_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города из списка"""
    query = update.callback_query
    await query.answer()
    
    city = query.data.replace("clientcity_", "")
    
    if city == "Другой город":
        await query.edit_message_text(
            "🏙 Напишите название вашего города:"
        )
        return REGISTER_CLIENT_CITY_OTHER
    else:
        context.user_data["city"] = city
        
        # Создаём профиль
        telegram_id = query.from_user.id
        
        logger.info(f"=== Создание профиля клиента ===")
        logger.info(f"Telegram ID: {telegram_id}")
        logger.info(f"Имя: {context.user_data.get('name')}")
        logger.info(f"Телефон: {context.user_data.get('phone')}")
        logger.info(f"Город: {city}")
        
        # Проверяем есть ли уже user (если добавляет вторую роль)
        existing_user = db.get_user(telegram_id)
        if existing_user:
            user_id = existing_user["id"]
            logger.info(f"Существующий user_id: {user_id}")
        else:
            user_id = db.create_user(telegram_id, "client")
            logger.info(f"Создан новый user_id: {user_id}")

        try:
            db.create_client_profile(
                user_id=user_id,
                name=context.user_data["name"],
                phone=context.user_data["phone"],
                city=context.user_data["city"],
                description="",
            )
            logger.info("✅ Профиль клиента успешно создан в БД!")
        except Exception as e:
            logger.error(f"❌ Ошибка создания профиля клиента: {e}", exc_info=True)
            await query.edit_message_text(
                f"❌ Ошибка создания профиля: {e}\n\nПопробуйте ещё раз."
            )
            context.user_data.clear()
            return ConversationHandler.END

        keyboard = [[InlineKeyboardButton("🏠 Моё меню заказчика", callback_data="show_client_menu")]]
        await query.edit_message_text(
            "🥳 <b>Профиль заказчика создан!</b>\n\n"
            "Теперь вы можете:\n"
            "• 📝 Создавать заказы\n"
            "• 🔍 Искать мастеров\n"
            "• 💬 Общаться с мастерами\n\n"
            "Детали о задаче вы опишете при создании заказа!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        context.user_data.clear()
        logger.info("✅ Context очищен")
        return ConversationHandler.END


async def register_client_city_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод другого города вручную"""
    city = update.message.text.strip()
    context.user_data["city"] = city
    
    # Создаём профиль
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
        description="",
    )

    keyboard = [[InlineKeyboardButton("🏠 Моё меню заказчика", callback_data="show_client_menu")]]
    await update.message.reply_text(
        "🥳 <b>Профиль заказчика создан!</b>\n\n"
        "Теперь вы можете:\n"
        "• 📝 Создавать заказы\n"
        "• 🔍 Искать мастеров\n"
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

    # Получаем текущий статус уведомлений
    user = db.get_user_by_telegram_id(update.effective_user.id)
    notifications_enabled = db.are_notifications_enabled(user['id']) if user else True
    notification_status = "🔔 Вкл" if notifications_enabled else "🔕 Выкл"

    keyboard = [
        [InlineKeyboardButton("📋 Доступные заказы", callback_data="worker_view_orders")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="worker_profile")],
        [InlineKeyboardButton(f"{notification_status} Уведомления", callback_data="toggle_notifications")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")],
    ]
    await query.edit_message_text(
        "🧰 <b>Меню мастера</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def toggle_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает уведомления для мастера"""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    # Получаем текущий статус
    current_status = db.are_notifications_enabled(user['id'])

    # Переключаем статус
    new_status = not current_status
    db.set_notifications_enabled(user['id'], new_status)

    status_text = "включены ✅" if new_status else "отключены ❌"

    await query.edit_message_text(
        f"🔔 <b>Уведомления {status_text}</b>\n\n"
        f"{'Вы будете получать уведомления о новых заказах в вашем городе и категориях.' if new_status else 'Вы НЕ будете получать уведомления о новых заказах. Вы можете просматривать заказы вручную в разделе \"Доступные заказы\".'}\n\n"
        "Возвращаемся в меню...",
        parse_mode="HTML"
    )

    # Возвращаемся в меню мастера через 2 секунды
    await asyncio.sleep(2)
    await show_worker_menu(update, context)


async def show_client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📝 Создать заказ", callback_data="client_create_order")],
        [InlineKeyboardButton("📂 Мои заказы", callback_data="client_my_orders")],
        [InlineKeyboardButton("🔍 Найти мастера", callback_data="client_browse_workers")],
        [InlineKeyboardButton("🧰 Главное меню", callback_data="go_main_menu")],
    ]
    await query.edit_message_text(
        "🏠 <b>Меню заказчика</b>\n\n"
        "Создайте заказ - мастера увидят его и откликнутся!\n"
        "Или найдите мастера самостоятельно.",
        parse_mode="HTML",
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
        profile_photo = profile_dict.get("profile_photo") or ""

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
        ]

        # Добавляем кнопку просмотра работ если они есть
        if photos_count > 0:
            keyboard.append([InlineKeyboardButton("📸 Посмотреть все работы", callback_data="view_portfolio")])

        # Добавляем кнопку отзывов если они есть
        if rating_count > 0:
            keyboard.append([InlineKeyboardButton(f"📊 Отзывы ({rating_count})", callback_data=f"show_reviews_worker_{user_id}")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")])

        # Показываем фото профиля (лицо), если есть. Иначе - первое из портфолио
        photo_to_show = profile_photo if profile_photo else (portfolio_photos.split(",")[0] if portfolio_photos else None)

        if photo_to_show:
            await query.message.reply_photo(
                photo=photo_to_show,
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
    """Обработка загружаемых фото (photo или document)"""

    # Если активен режим загрузки фото профиля - передаем управление туда
    if context.user_data.get("uploading_profile_photo"):
        return await upload_profile_photo(update, context)

    # Проверяем активен ли режим добавления фото
    if not context.user_data.get("adding_photos"):
        # Игнорируем фото если режим не активен
        logger.info("Получено фото но режим добавления не активен - игнорируем")
        return

    file_id = None

    # Обработка фото (сжатое изображение)
    if update.message and update.message.photo:
        logger.info("Получено фото (photo) для добавления в портфолио")
        photo = update.message.photo[-1]  # Берём самое большое разрешение
        file_id = photo.file_id

    # Обработка документа (файл без сжатия)
    elif update.message and update.message.document:
        document = update.message.document
        # Проверяем, что это изображение
        if document.mime_type and document.mime_type.startswith('image/'):
            logger.info("Получено фото (document) для добавления в портфолио")
            file_id = document.file_id
        else:
            keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
            await update.message.reply_text(
                "❌ Можно отправлять только изображения (JPG, PNG и т.д.).\n\n"
                "Попробуйте отправить фото еще раз.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    if not file_id:
        logger.warning("Не удалось получить file_id из сообщения")
        return

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

    logger.info(f"Нажата кнопка завершения добавления фото. Context: {context.user_data}")

    # Проверяем есть ли новые фото (более надежная проверка чем флаг adding_photos)
    new_photos = context.user_data.get("new_photos", [])
    has_new_photos = len(new_photos) > 0

    if not context.user_data.get("adding_photos") and not has_new_photos:
        logger.warning("Режим добавления фото не активен и нет новых фото!")
        try:
            await query.edit_message_text(
                "⚠️ Режим добавления фото не активен.\n\n"
                "Возможно произошла ошибка. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
                ])
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="⚠️ Режим добавления фото не активен.\n\nВозвращаемся в меню.",
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
    logger.info(f"Context user_data: {context.user_data}")

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
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        try:
            await query.message.reply_text(
                "⚠️ Вы не добавили ни одного фото.\n\nОперация отменена.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Не удалось отправить reply_text: {e}")
            # Пробуем через edit_message_text
            await query.edit_message_text(
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
            logger.info("Старое сообщение удалено")
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        # Отправляем НОВОЕ сообщение с результатом
        try:
            await query.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            logger.info("Новое сообщение отправлено успешно")
        except Exception as e:
            logger.error(f"Не удалось отправить новое сообщение через reply_text: {e}")
            # Пробуем через bot.send_message напрямую
            try:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML"
                )
                logger.info("Сообщение отправлено через bot.send_message")
            except Exception as e2:
                logger.error(f"Не удалось отправить через bot.send_message: {e2}")

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


# ------- ГАЛЕРЕЯ РАБОТ МАСТЕРА -------

async def view_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр галереи работ мастера с навигацией"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)

    if not user:
        await query.edit_message_text("❌ Пользователь не найден")
        return

    user_dict = dict(user)
    user_id = user_dict["id"]
    worker_profile = db.get_worker_profile(user_id)

    if not worker_profile:
        await query.edit_message_text("❌ Профиль мастера не найден")
        return

    profile_dict = dict(worker_profile)
    portfolio_photos = profile_dict.get("portfolio_photos") or ""

    if not portfolio_photos:
        await query.edit_message_text(
            "📸 У вас пока нет фото работ.\n\nДобавьте их через редактирование профиля.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")
            ]])
        )
        return

    photo_ids = [p.strip() for p in portfolio_photos.split(",") if p.strip()]

    # Сохраняем в context для навигации
    context.user_data['portfolio_photos'] = photo_ids
    context.user_data['current_portfolio_index'] = 0

    # Показываем первое фото
    keyboard = []

    # Навигация если фото больше одного
    if len(photo_ids) > 1:
        nav_buttons = [
            InlineKeyboardButton("◀️", callback_data="portfolio_prev"),
            InlineKeyboardButton(f"1/{len(photo_ids)}", callback_data="noop"),
            InlineKeyboardButton("▶️", callback_data="portfolio_next")
        ]
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")])

    try:
        await query.message.delete()
        await query.message.reply_photo(
            photo=photo_ids[0],
            caption=f"📸 <b>Фото работ</b>\n\n1 из {len(photo_ids)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка при показе галереи: {e}")
        await query.edit_message_text("❌ Ошибка при загрузке фото")


async def portfolio_navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по галерее работ"""
    query = update.callback_query
    await query.answer()

    photo_ids = context.user_data.get('portfolio_photos', [])
    current_index = context.user_data.get('current_portfolio_index', 0)

    if not photo_ids:
        return

    # Определяем направление
    if "prev" in query.data:
        current_index = (current_index - 1) % len(photo_ids)
    elif "next" in query.data:
        current_index = (current_index + 1) % len(photo_ids)

    context.user_data['current_portfolio_index'] = current_index

    # Формируем keyboard
    keyboard = []
    if len(photo_ids) > 1:
        nav_buttons = [
            InlineKeyboardButton("◀️", callback_data="portfolio_prev"),
            InlineKeyboardButton(f"{current_index + 1}/{len(photo_ids)}", callback_data="noop"),
            InlineKeyboardButton("▶️", callback_data="portfolio_next")
        ]
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")])

    try:
        await query.message.edit_media(
            media=query.message.photo[-1].file_id,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except:
        # Если edit_media не работает, удаляем и отправляем заново
        try:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.from_user.id,
                photo=photo_ids[current_index],
                caption=f"📸 <b>Фото работ</b>\n\n{current_index + 1} из {len(photo_ids)}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Ошибка навигации по галерее: {e}")


# ------- ЗАГРУЗКА ФОТО ПРОФИЛЯ -------

async def edit_profile_photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало загрузки/изменения фото профиля"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_photo = profile_dict.get("profile_photo")

    # Устанавливаем флаг загрузки фото профиля
    context.user_data['uploading_profile_photo'] = True
    context.user_data['user_id'] = user_id

    if current_photo:
        # Показываем текущее фото
        await query.message.delete()
        await query.message.reply_photo(
            photo=current_photo,
            caption=(
                "👤 <b>Текущее фото профиля</b>\n\n"
                "Отправьте новое фото, чтобы заменить это.\n\n"
                "Это фото будет показываться в вашем профиле."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_profile_photo")
            ]])
        )
    else:
        await query.edit_message_text(
            "👤 <b>Фото профиля</b>\n\n"
            "У вас пока нет фото профиля.\n\n"
            "Отправьте фото вашего лица, которое будет показываться в профиле.\n"
            "Это поможет клиентам узнать вас.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_profile_photo")
            ]])
        )


async def upload_profile_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загружаемого фото профиля"""

    # Проверяем активен ли режим загрузки фото профиля
    if not context.user_data.get("uploading_profile_photo"):
        logger.info("Получено фото но режим загрузки фото профиля не активен - игнорируем")
        return

    file_id = None

    # Обработка фото (сжатое изображение)
    if update.message and update.message.photo:
        logger.info("Получено фото профиля (photo)")
        photo = update.message.photo[-1]  # Берём самое большое разрешение
        file_id = photo.file_id

    # Обработка документа (файл без сжатия)
    elif update.message and update.message.document:
        document = update.message.document
        # Проверяем, что это изображение
        if document.mime_type and document.mime_type.startswith('image/'):
            logger.info("Получено фото профиля (document)")
            file_id = document.file_id
        else:
            await update.message.reply_text(
                "❌ Можно отправлять только изображения (JPG, PNG и т.д.).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data="cancel_profile_photo")
                ]])
            )
            return

    if not file_id:
        logger.warning("Не удалось получить file_id из сообщения")
        return

    # Сохраняем фото профиля в БД
    user_id = context.user_data.get('user_id')

    if user_id:
        try:
            db.update_worker_field(user_id, "profile_photo", file_id)
            logger.info(f"Фото профиля сохранено для user_id={user_id}")

            await update.message.reply_text(
                "✅ <b>Фото профиля успешно обновлено!</b>\n\n"
                "Теперь это фото будет показываться в вашем профиле.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👤 Посмотреть профиль", callback_data="worker_profile")],
                    [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
                ])
            )

            # Очищаем флаг
            context.user_data.clear()

        except Exception as e:
            logger.error(f"Ошибка при сохранении фото профиля: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при сохранении фото: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")
                ]])
            )
            context.user_data.clear()


async def cancel_profile_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена загрузки фото профиля"""
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "❌ Загрузка фото профиля отменена.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")
        ]])
    )


# ------- РЕДАКТИРОВАНИЕ ПРОФИЛЯ -------

async def show_edit_profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню редактирования профиля"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👤 Изменить фото профиля", callback_data="edit_profile_photo")],
        [InlineKeyboardButton("✏️ Изменить имя", callback_data="edit_name")],
        [InlineKeyboardButton("📱 Изменить телефон", callback_data="edit_phone")],
        [InlineKeyboardButton("🏙 Изменить город", callback_data="edit_city")],
        [InlineKeyboardButton("🔧 Изменить виды работ", callback_data="edit_categories")],
        [InlineKeyboardButton("📅 Изменить опыт", callback_data="edit_experience")],
        [InlineKeyboardButton("📝 Изменить описание", callback_data="edit_description")],
        [InlineKeyboardButton("📸 Добавить/изменить фото работ", callback_data="worker_add_photos")],
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

async def client_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр заказов клиента"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Получаем профиль клиента
        user = db.get_user(query.from_user.id)
        if not user:
            logger.error(f"User не найден для telegram_id: {query.from_user.id}")
            await query.edit_message_text(
                "❌ Ошибка: пользователь не найден.\n\nНажмите /start для регистрации.",
                parse_mode="HTML"
            )
            return
        
        logger.info(f"User найден: id={user['id']}")
        
        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            logger.error(f"Client profile не найден для user_id: {user['id']}")
            await query.edit_message_text(
                "❌ Ошибка: профиль клиента не найден.\n\n"
                "Возможно произошла ошибка при регистрации.\n"
                "Нажмите /start и зарегистрируйтесь заново.",
                parse_mode="HTML"
            )
            return
        
        logger.info(f"Client profile найден: id={client_profile['id']}")
        
        # Получаем заказы клиента (первые 10 с пагинацией)
        orders, total_count, has_next_page = db.get_client_orders(client_profile["id"], page=1, per_page=10)

        logger.info(f"Найдено заказов: {total_count} (показываем первые 10)")
        
        if not orders:
            keyboard = [
                [InlineKeyboardButton("📝 Создать первый заказ", callback_data="client_create_order")],
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")],
            ]
            
            await query.edit_message_text(
                "📂 <b>Мои заказы</b>\n\n"
                "У вас пока нет созданных заказов.\n\n"
                "Создайте первый заказ, чтобы начать получать отклики от мастеров!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # Формируем список заказов
        orders_text = "📂 <b>Мои заказы</b>\n\n"

        keyboard = []

        for i, order in enumerate(orders[:5], 1):  # Показываем последние 5
            order_dict = dict(order)
            order_id = order_dict['id']

            status_emoji = {
                "open": "🟢",
                "pending_choice": "🟡",
                "master_selected": "🔵",
                "contact_shared": "✅",
                "completed": "✅",
                "done": "✅",
                "canceled": "❌"
            }

            status_text = {
                "open": "Открыт",
                "pending_choice": "Ожидает выбора",
                "master_selected": "Мастер выбран",
                "contact_shared": "Контакт передан",
                "completed": "Завершён",
                "done": "Выполнен",
                "canceled": "Отменён"
            }

            emoji = status_emoji.get(order_dict.get("status", "open"), "⚪")
            status = status_text.get(order_dict.get("status", "open"), "Неизвестно")

            orders_text += f"{emoji} <b>Заказ #{order_dict['id']}</b> - {status}\n"
            orders_text += f"📍 {order_dict.get('city', 'Не указан')}\n"
            orders_text += f"🔧 {order_dict.get('category', 'Не указаны')}\n"

            # Показываем начало описания
            description = order_dict.get('description', '')
            if len(description) > 50:
                description = description[:50] + "..."
            orders_text += f"📝 {description}\n"

            # Количество фото
            photos = order_dict.get('photos', '')
            photos_count = len([p for p in photos.split(',') if p]) if photos else 0
            if photos_count > 0:
                orders_text += f"📸 {photos_count} фото\n"

            # Количество откликов
            bids_count = db.get_bids_count_for_order(order_id)
            if bids_count > 0:
                orders_text += f"💼 <b>{bids_count} {_get_bids_word(bids_count)}</b>\n"
                # Добавляем кнопку для просмотра откликов
                keyboard.append([InlineKeyboardButton(
                    f"💼 Откликов на заказ #{order_id}: {bids_count}",
                    callback_data=f"view_bids_{order_id}"
                )])

            orders_text += f"📅 {order_dict.get('created_at', '')}\n"
            orders_text += "\n"

        keyboard.append([InlineKeyboardButton("📝 Создать новый заказ", callback_data="client_create_order")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")])
        
        await query.edit_message_text(
            orders_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Ошибка в client_my_orders: {e}", exc_info=True)

        keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")]]

        await query.edit_message_text(
            f"❌ Ошибка при загрузке заказов:\n{str(e)}\n\nПопробуйте позже.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def view_order_bids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр откликов на заказ клиента с навигацией"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем order_id из callback_data
        order_id = int(query.data.replace("view_bids_", ""))

        # Проверяем что заказ принадлежит текущему пользователю
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text(
                "❌ Ошибка: пользователь не найден.",
                parse_mode="HTML"
            )
            return

        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            await query.edit_message_text(
                "❌ Ошибка: профиль клиента не найден.",
                parse_mode="HTML"
            )
            return

        # Получаем заказ
        order = db.get_order(order_id)
        if not order or order['client_id'] != client_profile['id']:
            await query.edit_message_text(
                "❌ Заказ не найден или у вас нет доступа к нему.",
                parse_mode="HTML"
            )
            return

        # Получаем все отклики
        bids = db.get_bids_for_order(order_id)

        if not bids:
            keyboard = [[InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")]]
            await query.edit_message_text(
                f"💼 <b>Отклики на заказ #{order_id}</b>\n\n"
                "Пока нет откликов от мастеров.\n\n"
                "Ожидайте, мастера скоро откликнутся!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Сохраняем отклики в контексте для навигации
        context.user_data['viewing_bids'] = {
            'order_id': order_id,
            'bids': [dict(bid) for bid in bids],
            'current_index': 0
        }

        # Показываем первый отклик
        await show_bid_card(update, context, query=query)

    except Exception as e:
        logger.error(f"Ошибка в view_order_bids: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")]]
        await query.edit_message_text(
            f"❌ Ошибка при загрузке откликов:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def show_bid_card(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """Показывает карточку отклика с информацией о мастере"""
    if not query:
        query = update.callback_query
        await query.answer()

    try:
        bid_data = context.user_data.get('viewing_bids')
        if not bid_data:
            await query.edit_message_text(
                "❌ Ошибка: данные откликов не найдены.",
                parse_mode="HTML"
            )
            return

        bids = bid_data['bids']
        current_index = bid_data['current_index']
        bid = bids[current_index]

        # Формируем текст карточки мастера
        text = f"💼 <b>Отклик {current_index + 1} из {len(bids)}</b>\n\n"

        text += f"👤 <b>{bid['worker_name']}</b>\n"

        # Рейтинг
        rating = bid.get('worker_rating', 0)
        rating_count = bid.get('worker_rating_count', 0)
        if rating > 0:
            stars = "⭐" * int(rating)
            text += f"{stars} {rating:.1f} ({rating_count} отзывов)\n"
        else:
            text += "⭐ Новый мастер (пока нет отзывов)\n"

        # Проверенные отзывы
        verified_reviews = bid.get('worker_verified_reviews', 0)
        if verified_reviews > 0:
            text += f"✅ {verified_reviews} проверенных отзывов\n"

        # Опыт
        experience = bid.get('worker_experience', '')
        if experience:
            text += f"📅 Опыт: {experience}\n"

        # Город
        city = bid.get('worker_city', '')
        if city:
            text += f"📍 Город: {city}\n"

        # Категории
        categories = bid.get('worker_categories', '')
        if categories:
            text += f"🔧 Услуги: {categories}\n"

        text += "\n"

        # Предложенная цена
        price = bid.get('price', 0)
        currency = bid.get('currency', 'BYN')
        text += f"💰 <b>Предложенная цена: {price} {currency}</b>\n\n"

        # Комментарий к отклику
        comment = bid.get('comment', '')
        if comment:
            text += f"💬 <b>Комментарий мастера:</b>\n{comment}\n\n"

        # Описание мастера
        description = bid.get('worker_description', '')
        if description:
            if len(description) > 200:
                description = description[:200] + "..."
            text += f"📝 <b>О мастере:</b>\n{description}\n\n"

        text += "💡 <i>Выберите этого мастера, чтобы получить доступ к его контактам</i>"

        # Кнопки навигации и действий
        keyboard = []

        # Навигация (если откликов больше 1)
        if len(bids) > 1:
            nav_buttons = []
            if current_index > 0:
                nav_buttons.append(InlineKeyboardButton("◀️ Предыдущий", callback_data="bid_prev"))
            nav_buttons.append(InlineKeyboardButton(
                f"{current_index + 1}/{len(bids)}",
                callback_data="noop"
            ))
            if current_index < len(bids) - 1:
                nav_buttons.append(InlineKeyboardButton("Следующий ▶️", callback_data="bid_next"))
            keyboard.append(nav_buttons)

        # Кнопка выбора мастера
        keyboard.append([InlineKeyboardButton(
            "✅ Выбрать этого мастера",
            callback_data=f"select_master_{bid['id']}"
        )])

        # Кнопка просмотра всех работ (если есть фото)
        portfolio_photos = bid.get('worker_portfolio_photos', '')
        if portfolio_photos:
            keyboard.append([InlineKeyboardButton(
                "📸 Посмотреть работы мастера",
                callback_data=f"view_worker_portfolio_{bid['worker_id']}"
            )])

        keyboard.append([InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")])

        # Отправляем с фото профиля мастера, если есть
        profile_photo = bid.get('worker_profile_photo', '')
        portfolio_photos_list = [p.strip() for p in portfolio_photos.split(',') if p.strip()] if portfolio_photos else []

        photo_to_show = profile_photo if profile_photo else (portfolio_photos_list[0] if portfolio_photos_list else None)

        if photo_to_show:
            # Удаляем старое сообщение и отправляем новое с фото
            try:
                await query.message.delete()
            except:
                pass

            await context.bot.send_photo(
                chat_id=query.from_user.id,
                photo=photo_to_show,
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Нет фото - просто редактируем текст
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"Ошибка в show_bid_card: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")]]
        await query.edit_message_text(
            f"❌ Ошибка при отображении отклика:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def bid_navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация между откликами"""
    query = update.callback_query
    await query.answer()

    try:
        bid_data = context.user_data.get('viewing_bids')
        if not bid_data:
            await query.edit_message_text("❌ Ошибка: данные откликов не найдены.")
            return

        bids = bid_data['bids']
        current_index = bid_data['current_index']

        if "prev" in query.data:
            current_index = max(0, current_index - 1)
        elif "next" in query.data:
            current_index = min(len(bids) - 1, current_index + 1)

        context.user_data['viewing_bids']['current_index'] = current_index

        await show_bid_card(update, context, query=query)

    except Exception as e:
        logger.error(f"Ошибка в bid_navigate: {e}", exc_info=True)


async def select_master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора мастера клиентом"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем bid_id из callback_data
        bid_id = int(query.data.replace("select_master_", ""))

        # Получаем информацию об отклике
        bids = context.user_data.get('viewing_bids', {}).get('bids', [])
        selected_bid = None
        for bid in bids:
            if bid['id'] == bid_id:
                selected_bid = bid
                break

        if not selected_bid:
            await query.edit_message_text(
                "❌ Ошибка: отклик не найден.",
                parse_mode="HTML"
            )
            return

        order_id = selected_bid['order_id']
        worker_name = selected_bid['worker_name']
        price = selected_bid['price']
        currency = selected_bid['currency']

        # Показываем окно подтверждения с оплатой
        text = (
            f"✅ <b>Вы выбрали мастера:</b>\n\n"
            f"👤 {worker_name}\n"
            f"💰 Цена: {price} {currency}\n\n"
            f"📞 <b>Для получения контакта мастера необходима оплата:</b>\n"
            f"💳 Стоимость доступа: <b>1 BYN</b> (или 10 Telegram Stars)\n\n"
            f"После оплаты вы получите:\n"
            f"• Контактный телефон мастера\n"
            f"• Возможность напрямую связаться с ним\n"
            f"• Мастер получит уведомление о вашем выборе\n\n"
            f"💡 <i>Выберите удобный способ оплаты:</i>"
        )

        keyboard = [
            [InlineKeyboardButton("⭐ Оплатить Telegram Stars", callback_data=f"pay_stars_{bid_id}")],
            [InlineKeyboardButton("💳 Оплатить картой", callback_data=f"pay_card_{bid_id}")],
            [InlineKeyboardButton("⬅️ Назад к откликам", callback_data=f"view_bids_{order_id}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в select_master: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Ошибка при выборе мастера:\n{str(e)}",
            parse_mode="HTML"
        )


async def pay_with_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплата через Telegram Stars"""
    query = update.callback_query
    await query.answer()

    try:
        bid_id = int(query.data.replace("pay_stars_", ""))

        # TODO: Интеграция с Telegram Stars Payment API
        # Здесь должна быть реальная интеграция с платежной системой Telegram Stars
        # На данный момент - заглушка для демонстрации

        text = (
            "⭐ <b>Оплата Telegram Stars</b>\n\n"
            "🚧 Функция оплаты через Telegram Stars находится в разработке.\n\n"
            "Для тестирования используйте кнопку ниже для имитации оплаты:"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Имитировать успешную оплату (тест)", callback_data=f"test_payment_success_{bid_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"select_master_{bid_id}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в pay_with_stars: {e}", exc_info=True)


async def pay_with_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплата картой через внешний платежный сервис"""
    query = update.callback_query
    await query.answer()

    try:
        bid_id = int(query.data.replace("pay_card_", ""))

        # TODO: Интеграция с внешней платежной системой (Stripe, BePaid, и т.д.)
        # Здесь должна быть реальная интеграция с платежным провайдером

        text = (
            "💳 <b>Оплата банковской картой</b>\n\n"
            "🚧 Функция оплаты картой находится в разработке.\n\n"
            "Планируется интеграция с:\n"
            "• BePaid (Беларусь)\n"
            "• Stripe (международные платежи)\n\n"
            "Для тестирования используйте кнопку ниже для имитации оплаты:"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Имитировать успешную оплату (тест)", callback_data=f"test_payment_success_{bid_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"select_master_{bid_id}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в pay_with_card: {e}", exc_info=True)


async def test_payment_success(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая функция для имитации успешной оплаты - создаёт чат вместо выдачи контакта"""
    query = update.callback_query
    await query.answer()

    try:
        bid_id = int(query.data.replace("test_payment_success_", ""))

        # Получаем информацию об отклике
        bids = context.user_data.get('viewing_bids', {}).get('bids', [])
        selected_bid = None
        for bid in bids:
            if bid['id'] == bid_id:
                selected_bid = bid
                break

        if not selected_bid:
            await query.edit_message_text("❌ Ошибка: отклик не найден.")
            return

        order_id = selected_bid['order_id']
        worker_id = selected_bid['worker_id']
        worker_name = selected_bid['worker_name']
        worker_telegram_id = selected_bid.get('worker_telegram_id')

        # Получаем информацию о клиенте
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Ошибка: пользователь не найден.")
            return

        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            await query.edit_message_text("❌ Ошибка: профиль клиента не найден.")
            return

        # 1. Создаём транзакцию (оплата 5 BYN за доступ)
        transaction_id = db.create_transaction(
            user_id=user["id"],
            order_id=order_id,
            bid_id=bid_id,
            transaction_type="master_contact_access",
            amount=5.00,
            currency="BYN",
            payment_method="test",
            description=f"Доступ к мастеру для заказа #{order_id}"
        )

        logger.info(f"✅ Транзакция #{transaction_id} создана: клиент {user['id']} оплатил доступ к мастеру {worker_id}")

        # 2. Получаем worker_user_id (из таблицы workers поле user_id)
        worker_profile = db.get_worker_by_id(worker_id)
        if not worker_profile:
            await query.edit_message_text("❌ Ошибка: профиль мастера не найден.")
            return

        worker_user_id = worker_profile['user_id']

        # 3. Проверяем существует ли уже чат
        existing_chat = db.get_chat_by_order_and_bid(order_id, bid_id)

        if existing_chat:
            chat_id = existing_chat['id']
            logger.info(f"Чат #{chat_id} уже существует, используем его")
        else:
            # Создаём новый чат
            chat_id = db.create_chat(
                order_id=order_id,
                client_user_id=user["id"],
                worker_user_id=worker_user_id,
                bid_id=bid_id
            )
            logger.info(f"✅ Чат #{chat_id} создан между клиентом {user['id']} и мастером {worker_user_id}")

        # 3. Отмечаем отклик как выбранный, НО заказ в статусе "waiting_master_confirmation"
        # Изменяем статус заказа
        db.update_order_status(order_id, "waiting_master_confirmation")

        # Отклик помечаем как selected
        db.select_bid(bid_id)

        # 4. Уведомляем мастера что его выбрали и открыт чат
        if worker_telegram_id:
            try:
                keyboard_for_worker = [
                    [InlineKeyboardButton("💬 Открыть чат", callback_data=f"open_chat_{chat_id}")],
                ]

                await context.bot.send_message(
                    chat_id=worker_telegram_id,
                    text=(
                        f"🎉 <b>Ваш отклик выбран!</b>\n\n"
                        f"Клиент выбрал вас для выполнения заказа #{order_id}\n\n"
                        f"💬 Открыт чат для обсуждения деталей.\n"
                        f"⚠️ <b>ВАЖНО:</b> Ответьте клиенту в течение 24 часов, иначе ваш рейтинг снизится!\n\n"
                        f"Обсудите детали заказа и подтвердите готовность выполнить работу."
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard_for_worker)
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления мастеру: {e}")

        # 5. Показываем клиенту что чат открыт
        text = (
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"👤 <b>Выбран мастер:</b> {worker_name}\n\n"
            f"💬 <b>Открыт чат для обсуждения деталей</b>\n\n"
            f"📋 <b>Следующие шаги:</b>\n"
            f"1. Обсудите с мастером детали заказа в чате\n"
            f"2. Дождитесь подтверждения мастера (до 24 часов)\n"
            f"3. Договоритесь о времени и месте встречи\n\n"
            f"💡 Если мастер не ответит в течение 24 часов, вы сможете выбрать другого мастера БЕЗ дополнительной оплаты.\n\n"
            f"Удачного сотрудничества! 🤝"
        )

        keyboard = [
            [InlineKeyboardButton("💬 Открыть чат", callback_data=f"open_chat_{chat_id}")],
            [InlineKeyboardButton("📂 Мои заказы", callback_data="client_my_orders")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="show_client_menu")],
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Очищаем контекст просмотра откликов
        if 'viewing_bids' in context.user_data:
            del context.user_data['viewing_bids']

    except Exception as e:
        logger.error(f"Ошибка в test_payment_success: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Ошибка при обработке оплаты:\n{str(e)}",
            parse_mode="HTML"
        )


# ============================================
# СИСТЕМА ЧАТОВ
# ============================================

async def open_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает чат между клиентом и мастером"""
    query = update.callback_query
    await query.answer()

    try:
        chat_id = int(query.data.replace("open_chat_", ""))

        # Получаем информацию о чате
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            await query.edit_message_text("❌ Чат не найден.")
            return

        chat_dict = dict(chat)

        # Проверяем что пользователь участник этого чата
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        is_client = user_dict['id'] == chat_dict['client_user_id']
        is_worker = user_dict['id'] == chat_dict['worker_user_id']

        if not is_client and not is_worker:
            await query.edit_message_text("❌ У вас нет доступа к этому чату.")
            return

        # Определяем роль пользователя
        my_role = "client" if is_client else "worker"
        other_role = "worker" if is_client else "client"

        # Получаем информацию о собеседнике
        if is_client:
            worker = db.get_user_by_id(chat_dict['worker_user_id'])
            worker_profile = db.get_worker_profile(worker['id']) if worker else None
            other_name = worker_profile['name'] if worker_profile else "Мастер"
        else:
            client = db.get_user_by_id(chat_dict['client_user_id'])
            client_profile = db.get_client_profile(client['id']) if client else None
            other_name = client_profile['name'] if client_profile else "Клиент"

        # Получаем последние сообщения
        messages = db.get_chat_messages(chat_id, limit=10)
        messages_list = list(reversed(messages))  # Старые сверху, новые снизу

        # Отмечаем сообщения как прочитанные
        db.mark_messages_as_read(chat_id, user_dict['id'])

        # Формируем текст чата
        text = f"💬 <b>Чат с {other_name}</b>\n"
        text += f"📋 Заказ #{chat_dict['order_id']}\n\n"

        if messages_list:
            text += "<b>История сообщений:</b>\n\n"
            for msg in messages_list:
                msg_dict = dict(msg)
                sender_role = msg_dict['sender_role']
                message_text = msg_dict['message_text']
                created_at = msg_dict['created_at'][:16]  # Обрезаем до минут

                if sender_role == my_role:
                    text += f"<b>Вы:</b> {message_text}\n"
                else:
                    text += f"<b>{other_name}:</b> {message_text}\n"
                text += f"<i>{created_at}</i>\n\n"
        else:
            text += "<i>Пока нет сообщений</i>\n\n"

        text += "💡 Напишите сообщение для отправки в чат:"

        # Сохраняем chat_id в контексте для отправки сообщения
        context.user_data['active_chat_id'] = chat_id
        context.user_data['active_chat_role'] = my_role

        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"open_chat_{chat_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="show_client_menu" if is_client else "show_worker_menu")],
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в open_chat: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Ошибка при открытии чата:\n{str(e)}")


async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщения, отправленные в активный чат"""
    # Проверяем есть ли активный чат
    chat_id = context.user_data.get('active_chat_id')
    my_role = context.user_data.get('active_chat_role')

    if not chat_id or not my_role:
        # Нет активного чата, пропускаем
        return

    message_text = update.message.text

    if not message_text:
        return

    try:
        # Получаем информацию о пользователе
        user = db.get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("❌ Пользователь не найден.")
            return

        user_dict = dict(user)

        # Отправляем сообщение в чат
        message_id = db.send_message(chat_id, user_dict['id'], my_role, message_text)

        logger.info(f"✅ Сообщение #{message_id} отправлено в чат #{chat_id} от {my_role}")

        # Если это первое сообщение мастера - подтверждаем готовность
        if my_role == "worker" and not db.is_worker_confirmed(chat_id):
            db.confirm_worker_in_chat(chat_id)
            logger.info(f"✅ Мастер подтвердил готовность в чате #{chat_id}")

            # Обновляем статус заказа
            chat = db.get_chat_by_id(chat_id)
            if chat:
                db.update_order_status(chat['order_id'], "master_confirmed")
                logger.info(f"✅ Заказ #{chat['order_id']} переведён в статус 'master_confirmed'")

        # Получаем информацию о чате для уведомления
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            await update.message.reply_text("❌ Чат не найден.")
            return

        chat_dict = dict(chat)

        # Уведомляем собеседника о новом сообщении
        other_user_id = chat_dict['worker_user_id'] if my_role == "client" else chat_dict['client_user_id']
        other_user = db.get_user_by_id(other_user_id)

        if other_user:
            other_user_dict = dict(other_user)
            try:
                # Получаем имя отправителя
                if my_role == "client":
                    client_profile = db.get_client_profile(user_dict['id'])
                    sender_name = client_profile['name'] if client_profile else "Клиент"
                else:
                    worker_profile = db.get_worker_profile(user_dict['id'])
                    sender_name = worker_profile['name'] if worker_profile else "Мастер"

                await context.bot.send_message(
                    chat_id=other_user_dict['telegram_id'],
                    text=(
                        f"💬 <b>Новое сообщение от {sender_name}</b>\n"
                        f"📋 Заказ #{chat_dict['order_id']}\n\n"
                        f"{message_text}"
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("💬 Открыть чат", callback_data=f"open_chat_{chat_id}")
                    ]])
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления: {e}")

        # Подтверждаем отправку
        await update.message.reply_text(
            "✅ Сообщение отправлено!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 Открыть чат", callback_data=f"open_chat_{chat_id}")
            ]])
        )

    except Exception as e:
        logger.error(f"Ошибка в handle_chat_message: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка при отправке сообщения:\n{str(e)}")


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


async def add_test_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления тестовых заказов (только для user_id 641830790)"""
    telegram_id = update.effective_user.id

    # Вызываем функцию из db.py
    success, message, count = db.add_test_orders(telegram_id)

    await update.message.reply_text(message)


async def add_test_workers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления тестовых мастеров и откликов (только для user_id 641830790)"""
    telegram_id = update.effective_user.id

    # Вызываем функцию из db.py
    success, message, count = db.add_test_workers(telegram_id)

    await update.message.reply_text(message)


# ------- ПРОСМОТР ЗАКАЗОВ ДЛЯ МАСТЕРОВ -------

async def worker_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр доступных заказов для мастера"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Получаем профиль мастера
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Ошибка: пользователь не найден.")
            return
        
        worker_profile = db.get_worker_profile(user["id"])
        if not worker_profile:
            await query.edit_message_text("❌ Ошибка: профиль мастера не найден.")
            return
        
        worker_dict = dict(worker_profile)
        categories = worker_dict.get("categories", "").split(", ")
        
        # Собираем заказы по категориям мастера (с пагинацией - первые 10 на категорию)
        all_orders = []
        seen_order_ids = set()

        for category in categories:
            if category.strip():
                orders, _, _ = db.get_orders_by_category(category.strip(), page=1, per_page=10)
                for order in orders:
                    order_dict = dict(order)
                    if order_dict['id'] not in seen_order_ids:
                        all_orders.append(order_dict)
                        seen_order_ids.add(order_dict['id'])
        
        # Сортируем по дате (новые первые)
        all_orders.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        if not all_orders:
            keyboard = [
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")],
            ]
            
            await query.edit_message_text(
                "📋 <b>Доступные заказы</b>\n\n"
                f"🔧 Ваши категории: <i>{worker_dict.get('categories', 'Не указаны')}</i>\n\n"
                "Пока нет открытых заказов по вашим категориям.\n\n"
                "Как только появятся новые заказы, вы их увидите здесь!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # Показываем список заказов
        orders_text = "📋 <b>Доступные заказы</b>\n\n"
        orders_text += f"🔧 Ваши категории: <i>{worker_dict.get('categories', 'Не указаны')}</i>\n\n"
        orders_text += f"Найдено заказов: <b>{len(all_orders)}</b>\n\n"
        
        # Показываем первые 5 заказов
        keyboard = []
        for i, order in enumerate(all_orders[:5], 1):
            orders_text += f"🟢 <b>Заказ #{order['id']}</b>\n"
            orders_text += f"📍 Город: {order.get('city', 'Не указан')}\n"
            orders_text += f"🔧 Категория: {order.get('category', 'Не указана')}\n"
            
            # Описание (сокращённое)
            description = order.get('description', '')
            if len(description) > 80:
                description = description[:80] + "..."
            orders_text += f"📝 {description}\n"
            
            # Фото
            photos = order.get('photos', '')
            photos_count = len([p for p in photos.split(',') if p]) if photos else 0
            if photos_count > 0:
                orders_text += f"📸 {photos_count} фото\n"
            
            orders_text += f"📅 {order.get('created_at', '')}\n"
            orders_text += "\n"
            
            # Добавляем кнопку для просмотра деталей
            keyboard.append([InlineKeyboardButton(
                f"👁 Заказ #{order['id']} - Подробнее", 
                callback_data=f"view_order_{order['id']}"
            )])
        
        if len(all_orders) > 5:
            orders_text += f"<i>... и ещё {len(all_orders) - 5} заказов</i>\n\n"
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")])
        
        await query.edit_message_text(
            orders_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре заказов: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка при загрузке заказов.\n\n"
            "Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
            ])
        )


async def worker_view_order_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный просмотр заказа мастером"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Извлекаем order_id из callback_data
        order_id = int(query.data.replace("view_order_", ""))
        
        # Получаем заказ
        order = db.get_order_by_id(order_id)
        if not order:
            await query.edit_message_text("❌ Заказ не найден.")
            return
        
        order_dict = dict(order)
        
        # Проверяем есть ли уже отклик от этого мастера
        user = db.get_user(query.from_user.id)
        worker_profile = db.get_worker_profile(user["id"])
        
        already_bid = db.check_worker_bid_exists(order_id, worker_profile["id"])
        
        # Формируем текст
        text = f"📋 <b>Заказ #{order_id}</b>\n\n"
        text += f"📍 <b>Город:</b> {order_dict.get('city', 'Не указан')}\n"
        text += f"🔧 <b>Категория:</b> {order_dict.get('category', 'Не указана')}\n"
        text += f"📅 <b>Создан:</b> {order_dict.get('created_at', '')}\n\n"
        text += f"📝 <b>Описание:</b>\n{order_dict.get('description', 'Нет описания')}\n\n"
        
        # Информация о клиенте
        text += f"👤 <b>Заказчик:</b> {order_dict.get('client_name', 'Неизвестно')}\n"
        client_rating = order_dict.get('client_rating', 0)
        client_rating_count = order_dict.get('client_rating_count', 0)
        if client_rating_count > 0:
            text += f"⭐ {client_rating:.1f} ({client_rating_count} отзывов)\n"
        
        # Получаем фото
        photos = order_dict.get('photos', '')
        photo_ids = [p.strip() for p in photos.split(',') if p.strip()]
        
        if photo_ids:
            # Отправляем первое фото с текстом
            context.user_data['current_order_id'] = order_id
            context.user_data['order_photos'] = photo_ids
            context.user_data['current_photo_index'] = 0
            
            keyboard = []
            
            # Навигация по фото если их больше 1
            if len(photo_ids) > 1:
                nav_buttons = []
                if len(photo_ids) > 1:
                    nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"order_photo_prev_{order_id}"))
                nav_buttons.append(InlineKeyboardButton(f"1/{len(photo_ids)}", callback_data="noop"))
                if len(photo_ids) > 1:
                    nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"order_photo_next_{order_id}"))
                keyboard.append(nav_buttons)
            
            # Кнопка завершения заказа если мастер работает над ним
            order_status = order_dict.get('status', 'open')
            selected_worker_id = order_dict.get('selected_worker_id')

            if order_status == 'in_progress' and selected_worker_id == worker_profile["id"]:
                keyboard.append([InlineKeyboardButton("✅ Работа завершена", callback_data=f"worker_complete_order_{order_id}")])
            # Кнопка отклика (только для открытых заказов)
            elif order_status == 'open':
                if already_bid:
                    keyboard.append([InlineKeyboardButton("✅ Вы уже откликнулись", callback_data="noop")])
                else:
                    keyboard.append([InlineKeyboardButton("💰 Откликнуться", callback_data=f"bid_on_order_{order_id}")])

            keyboard.append([InlineKeyboardButton("⬅️ К списку заказов", callback_data="worker_view_orders")])
            
            await query.message.delete()
            await query.message.reply_photo(
                photo=photo_ids[0],
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Нет фото - просто текст
            keyboard = []

            # Кнопка завершения заказа если мастер работает над ним
            order_status = order_dict.get('status', 'open')
            selected_worker_id = order_dict.get('selected_worker_id')

            if order_status == 'in_progress' and selected_worker_id == worker_profile["id"]:
                keyboard.append([InlineKeyboardButton("✅ Работа завершена", callback_data=f"worker_complete_order_{order_id}")])
            # Кнопка отклика (только для открытых заказов)
            elif order_status == 'open':
                if already_bid:
                    keyboard.append([InlineKeyboardButton("✅ Вы уже откликнулись", callback_data="noop")])
                else:
                    keyboard.append([InlineKeyboardButton("💰 Откликнуться", callback_data=f"bid_on_order_{order_id}")])

            keyboard.append([InlineKeyboardButton("⬅️ К списку заказов", callback_data="worker_view_orders")])
            
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"Ошибка при просмотре деталей заказа: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка.\n\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
            ]])
        )


async def worker_order_photo_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по фото заказа"""
    query = update.callback_query
    await query.answer()
    
    try:
        photo_ids = context.user_data.get('order_photos', [])
        current_index = context.user_data.get('current_photo_index', 0)
        order_id = context.user_data.get('current_order_id')
        
        if not photo_ids or order_id is None:
            return
        
        # Определяем направление
        if "prev" in query.data:
            current_index = (current_index - 1) % len(photo_ids)
        elif "next" in query.data:
            current_index = (current_index + 1) % len(photo_ids)
        
        context.user_data['current_photo_index'] = current_index
        
        # Получаем заказ для caption
        order = db.get_order_by_id(order_id)
        order_dict = dict(order)
        
        # Проверяем отклик
        user = db.get_user(query.from_user.id)
        worker_profile = db.get_worker_profile(user["id"])
        already_bid = db.check_worker_bid_exists(order_id, worker_profile["id"])
        
        # Формируем текст
        text = f"📋 <b>Заказ #{order_id}</b>\n\n"
        text += f"📍 <b>Город:</b> {order_dict.get('city', 'Не указан')}\n"
        text += f"🔧 <b>Категория:</b> {order_dict.get('category', 'Не указана')}\n"
        text += f"📅 <b>Создан:</b> {order_dict.get('created_at', '')}\n\n"
        text += f"📝 <b>Описание:</b>\n{order_dict.get('description', 'Нет описания')}\n\n"
        text += f"👤 <b>Заказчик:</b> {order_dict.get('client_name', 'Неизвестно')}\n"
        
        # Обновляем кнопки
        keyboard = []
        nav_buttons = []
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"order_photo_prev_{order_id}"))
        nav_buttons.append(InlineKeyboardButton(f"{current_index+1}/{len(photo_ids)}", callback_data="noop"))
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"order_photo_next_{order_id}"))
        keyboard.append(nav_buttons)
        
        if already_bid:
            keyboard.append([InlineKeyboardButton("✅ Вы уже откликнулись", callback_data="noop")])
        else:
            keyboard.append([InlineKeyboardButton("💰 Откликнуться", callback_data=f"bid_on_order_{order_id}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ К списку заказов", callback_data="worker_view_orders")])
        
        # Обновляем фото
        await query.message.edit_media(
            media=query.message.photo[0].file_id if hasattr(query.message, 'photo') else photo_ids[current_index],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await query.message.edit_caption(
            caption=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Ошибка навигации по фото: {e}", exc_info=True)


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


# ------- ОТКЛИКИ МАСТЕРОВ НА ЗАКАЗЫ -------

async def worker_bid_on_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания отклика - ввод цены"""
    query = update.callback_query
    await query.answer()

    # Извлекаем order_id
    order_id = int(query.data.replace("bid_on_order_", ""))
    context.user_data['bid_order_id'] = order_id

    # Проверяем не откликался ли уже
    user = db.get_user(query.from_user.id)
    user_dict = dict(user) if user else {}
    worker_profile = db.get_worker_profile(user_dict.get("id"))

    if not worker_profile:
        await query.answer("Ошибка: профиль мастера не найден", show_alert=True)
        return ConversationHandler.END

    profile_dict = dict(worker_profile)
    worker_id = profile_dict.get("id")

    if db.check_worker_bid_exists(order_id, worker_id):
        await query.answer("Вы уже откликнулись на этот заказ!", show_alert=True)
        return ConversationHandler.END

    text = (
        "💰 <b>Ваш отклик на заказ</b>\n\n"
        "⚠️ <b>ВНИМАНИЕ:</b> Цену изменить будет НЕЛЬЗЯ!\n\n"
        "Введите вашу цену (только число):\n"
        "Например: <code>150</code>"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_bid")
    ]])

    # Пробуем отредактировать как caption (если есть фото), иначе как text
    try:
        await query.edit_message_caption(
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except:
        # Если не получилось (нет фото), редактируем текст
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    return BID_ENTER_PRICE


async def worker_bid_enter_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода цены"""
    price_text = update.message.text.strip()
    
    # Проверяем что это число
    try:
        price = float(price_text.replace(',', '.'))
        if price <= 0:
            raise ValueError
    except:
        await update.message.reply_text(
            "❌ Пожалуйста, введите корректную цену (только число).\n\n"
            "Например: <code>150</code> или <code>99.50</code>",
            parse_mode="HTML"
        )
        return BID_ENTER_PRICE
    
    context.user_data['bid_price'] = price
    
    # Выбор валюты
    keyboard = [
        [
            InlineKeyboardButton("BYN (₽)", callback_data="bid_currency_BYN"),
            InlineKeyboardButton("USD ($)", callback_data="bid_currency_USD"),
        ],
        [
            InlineKeyboardButton("EUR (€)", callback_data="bid_currency_EUR"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_bid")],
    ]
    
    await update.message.reply_text(
        f"💵 Выберите валюту для цены <b>{price}</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return BID_SELECT_CURRENCY


async def worker_bid_select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора валюты"""
    query = update.callback_query
    await query.answer()
    
    currency = query.data.replace("bid_currency_", "")
    context.user_data['bid_currency'] = currency
    
    price = context.user_data['bid_price']
    
    # Спрашиваем комментарий
    await query.edit_message_text(
        f"💰 Ваша цена: <b>{price} {currency}</b>\n\n"
        "📝 Хотите добавить комментарий?\n"
        "(Например: \"Могу завтра утром\" или \"Есть все материалы\")\n\n"
        "Напишите комментарий или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Пропустить", callback_data="bid_skip_comment"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_bid")
        ]])
    )
    
    return BID_ENTER_COMMENT


async def worker_bid_enter_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода комментария"""
    comment = update.message.text.strip()
    context.user_data['bid_comment'] = comment
    
    return await worker_bid_publish(update, context)


async def worker_bid_skip_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск комментария"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['bid_comment'] = ""
    
    return await worker_bid_publish(update, context)


async def worker_bid_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Публикация отклика"""
    try:
        # Получаем данные
        order_id = context.user_data['bid_order_id']
        price = context.user_data['bid_price']
        currency = context.user_data['bid_currency']
        comment = context.user_data.get('bid_comment', '')
        
        # Получаем worker_id
        if hasattr(update, 'callback_query'):
            telegram_id = update.callback_query.from_user.id
            message = update.callback_query.message
        else:
            telegram_id = update.effective_user.id
            message = update.message
        
        user = db.get_user(telegram_id)
        worker_profile = db.get_worker_profile(user["id"])
        
        # Создаём отклик (может вызвать ValueError при rate limiting)
        try:
            bid_id = db.create_bid(
                order_id=order_id,
                worker_id=worker_profile["id"],
                proposed_price=price,
                currency=currency,
                comment=comment
            )
        except ValueError as e:
            # Rate limiting error
            if hasattr(update, 'callback_query'):
                message = update.callback_query.message
            else:
                message = update.message

            await message.reply_text(
                str(e),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
                ]])
            )
            context.user_data.clear()
            return ConversationHandler.END

        logger.info(f"✅ Отклик #{bid_id} создан мастером {worker_profile['id']} на заказ {order_id}")

        # Отправляем уведомление клиенту
        order = db.get_order_by_id(order_id)
        if order:
            # Получаем telegram_id клиента
            client = db.get_client_by_id(order['client_id'])
            client_user = db.get_user_by_id(client['user_id'])

            worker_name = worker_profile.get('name', 'Мастер')

            # Используем новую функцию уведомления
            await notify_client_new_bid(
                context,
                client_user['telegram_id'],
                order_id,
                worker_name,
                price,
                currency
            )
        
        # Подтверждение мастеру
        keyboard = [[InlineKeyboardButton("📋 К доступным заказам", callback_data="worker_view_orders")]]
        
        await message.reply_text(
            "✅ <b>Отклик отправлен!</b>\n\n"
            f"💰 Ваша цена: {price} {currency}\n"
            f"📝 Комментарий: {comment if comment else 'Нет'}\n\n"
            "Клиент увидит ваш отклик и сможет с вами связаться!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка создания отклика: {e}", exc_info=True)
        
        if hasattr(update, 'callback_query'):
            message = update.callback_query.message
        else:
            message = update.message
            
        await message.reply_text(
            "❌ Произошла ошибка при создании отклика.\n\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
            ]])
        )
        context.user_data.clear()
        return ConversationHandler.END


async def worker_bid_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена создания отклика"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "❌ Создание отклика отменено.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 К доступным заказам", callback_data="worker_view_orders")
        ]])
    )
    
    context.user_data.clear()
    return ConversationHandler.END


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


# ------- СОЗДАНИЕ ЗАКАЗА -------

async def client_create_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания заказа - выбор города"""
    query = update.callback_query
    await query.answer()
    
    # Получаем профиль клиента
    user = db.get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("Ошибка: пользователь не найден")
        return ConversationHandler.END
    
    client_profile = db.get_client_profile(user["id"])
    if not client_profile:
        await query.edit_message_text("Ошибка: профиль клиента не найден")
        return ConversationHandler.END
    
    # Сохраняем client_id
    context.user_data["order_client_id"] = client_profile["id"]
    
    # Предлагаем выбор города
    cities = [
        "Минск", "Гомель", "Могилёв", "Витебск",
        "Гродно", "Брест", "Бобруйск", "Барановичи",
        "Борисов", "Пинск", "Орша", "Мозырь",
        "Новополоцк", "Лида", "Солигорск",
        "Другой город"
    ]
    
    keyboard = []
    row = []
    for i, city in enumerate(cities):
        row.append(InlineKeyboardButton(city, callback_data=f"ordercity_{city}"))
        if len(row) == 2 or i == len(cities) - 1:
            keyboard.append(row)
            row = []
    
    await query.edit_message_text(
        "📝 <b>Создание заказа</b>\n\n"
        "🏙 <b>Шаг 1:</b> В каком городе нужна работа?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CREATE_ORDER_CITY


async def create_order_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города для заказа"""
    query = update.callback_query
    await query.answer()
    
    city = query.data.replace("ordercity_", "")
    
    if city == "Другой город":
        await query.edit_message_text(
            "🏙 Напишите название города:"
        )
        return CREATE_ORDER_CITY
    else:
        context.user_data["order_city"] = city
        
        # Переходим к выбору категорий
        keyboard = [
            [
                InlineKeyboardButton("Электрика", callback_data="ordercat_Электрика"),
                InlineKeyboardButton("Сантехника", callback_data="ordercat_Сантехника"),
            ],
            [
                InlineKeyboardButton("Отделка", callback_data="ordercat_Отделка"),
                InlineKeyboardButton("Сборка мебели", callback_data="ordercat_Сборка мебели"),
            ],
            [
                InlineKeyboardButton("Окна/двери", callback_data="ordercat_Окна/двери"),
                InlineKeyboardButton("Бытовая техника", callback_data="ordercat_Бытовая техника"),
            ],
            [
                InlineKeyboardButton("Напольные покрытия", callback_data="ordercat_Напольные покрытия"),
                InlineKeyboardButton("Мелкий ремонт", callback_data="ordercat_Мелкий ремонт"),
            ],
            [
                InlineKeyboardButton("Дизайн", callback_data="ordercat_Дизайн"),
            ],
            [InlineKeyboardButton("✅ Завершить выбор", callback_data="ordercat_done")],
        ]
        
        context.user_data["order_categories"] = []
        
        await query.edit_message_text(
            f"Город: <b>{city}</b>\n\n"
            "🔧 <b>Шаг 2:</b> Какие работы нужны?\n\n"
            "Выберите 1-3 категории.\n"
            "💡 <i>Выбирайте категории как можно точнее - так мастера быстрее увидят ваш заказ!</i>\n\n"
            "Нажмите «✅ Завершить выбор» когда готово.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_ORDER_CATEGORIES


async def create_order_categories_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора категорий для заказа"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    selected = data.replace("ordercat_", "")
    
    if selected == "done":
        if not context.user_data.get("order_categories"):
            await query.answer("Выберите хотя бы одну категорию!", show_alert=True)
            return CREATE_ORDER_CATEGORIES
        
        # Переходим к описанию
        categories_text = ", ".join(context.user_data["order_categories"])
        
        await query.edit_message_text(
            f"Город: <b>{context.user_data['order_city']}</b>\n"
            f"Категории: <b>{categories_text}</b>\n\n"
            "📝 <b>Шаг 3:</b> Опишите что нужно сделать\n\n"
            "Например:\n"
            "• Заменить розетки в 3 комнатах\n"
            "• Установить смеситель на кухне\n"
            "• Повесить люстру\n\n"
            "Чем подробнее - тем точнее мастер назовёт цену!",
            parse_mode="HTML"
        )
        return CREATE_ORDER_DESCRIPTION
    
    else:
        # Добавляем/убираем категорию
        if "order_categories" not in context.user_data:
            context.user_data["order_categories"] = []
        
        if selected not in context.user_data["order_categories"]:
            if len(context.user_data["order_categories"]) >= 3:
                await query.answer("Максимум 3 категории!", show_alert=True)
                return CREATE_ORDER_CATEGORIES
            
            context.user_data["order_categories"].append(selected)
            await query.answer(f"✅ Добавлено: {selected}")
        else:
            context.user_data["order_categories"].remove(selected)
            await query.answer(f"❌ Убрано: {selected}")
        
        return CREATE_ORDER_CATEGORIES


async def create_order_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка описания заказа"""
    description = update.message.text.strip()
    
    if len(description) < 10:
        await update.message.reply_text(
            "⚠️ Опишите подробнее (минимум 10 символов)"
        )
        return CREATE_ORDER_DESCRIPTION
    
    context.user_data["order_description"] = description
    
    # Предлагаем загрузить фото
    keyboard = [[InlineKeyboardButton("⏭ Пропустить фото", callback_data="order_skip_photos")]]
    
    await update.message.reply_text(
        "📸 <b>Шаг 4:</b> Загрузите фото объекта (до 5 штук)\n\n"
        "Фото помогут мастеру точнее оценить работу.\n"
        "Можете пропустить этот шаг.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    context.user_data["order_photos"] = []
    return CREATE_ORDER_PHOTOS


async def create_order_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загрузки фото для заказа"""
    
    if "order_photos" not in context.user_data:
        context.user_data["order_photos"] = []
    
    photos = context.user_data["order_photos"]
    
    if len(photos) >= 5:
        await update.message.reply_text(
            "⚠️ Максимум 5 фото. Нажмите кнопку для завершения."
        )
        return CREATE_ORDER_PHOTOS
    
    # Сохраняем file_id
    file_id = update.message.photo[-1].file_id
    photos.append(file_id)
    
    keyboard = [[InlineKeyboardButton("✅ Завершить и опубликовать", callback_data="order_publish")]]
    
    await update.message.reply_text(
        f"✅ Фото {len(photos)}/5 добавлено!\n\n"
        f"Можете добавить ещё или завершить.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return CREATE_ORDER_PHOTOS


async def create_order_skip_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск загрузки фото"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["order_photos"] = []
    
    return await create_order_publish(update, context)


async def create_order_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Публикация заказа"""
    
    if hasattr(update, 'callback_query'):
        query = update.callback_query
        await query.answer()
        message = query.message
    else:
        message = update.message
    
    try:
        logger.info("=== Публикация заказа ===")
        logger.info(f"client_id: {context.user_data.get('order_client_id')}")
        logger.info(f"city: {context.user_data.get('order_city')}")
        logger.info(f"categories: {context.user_data.get('order_categories')}")
        logger.info(f"description: {context.user_data.get('order_description')}")
        logger.info(f"photos: {len(context.user_data.get('order_photos', []))}")
        
        # Создаём заказ в БД (может вызвать ValueError при rate limiting)
        try:
            order_id = db.create_order(
                client_id=context.user_data["order_client_id"],
                city=context.user_data["order_city"],
                categories=context.user_data["order_categories"],
                description=context.user_data["order_description"],
                photos=context.user_data.get("order_photos", [])
            )
        except ValueError as e:
            # Rate limiting error
            keyboard = [[InlineKeyboardButton("⬅️ В меню", callback_data="show_client_menu")]]
            await message.reply_text(
                str(e),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data.clear()
            return ConversationHandler.END

        logger.info(f"✅ Заказ #{order_id} успешно сохранён в БД!")

        # Получаем созданный заказ для отправки уведомлений
        order = db.get_order_by_id(order_id)
        if order:
            order_dict = dict(order)

            # Находим всех мастеров в нужных категориях И городе и отправляем уведомления
            notified_workers = set()  # Чтобы не уведомлять одного мастера несколько раз
            order_city = context.user_data['order_city']

            for category in context.user_data["order_categories"]:
                # ВАЖНО: фильтруем мастеров по городу И категории
                workers, _, _ = db.get_all_workers(city=order_city, category=category)
                for worker in workers:
                    worker_dict = dict(worker)
                    worker_id = worker_dict['id']

                    if worker_id in notified_workers:
                        continue

                    worker_user = db.get_user_by_id(worker_dict['user_id'])
                    if worker_user:
                        # Проверяем включены ли уведомления у мастера
                        if db.are_notifications_enabled(worker_dict['user_id']):
                            await notify_worker_new_order(
                                context,
                                worker_user['telegram_id'],
                                order_dict
                            )
                            notified_workers.add(worker_id)

        categories_text = ", ".join(context.user_data["order_categories"])
        photos_count = len(context.user_data.get("order_photos", []))

        keyboard = [
            [InlineKeyboardButton("📂 Мои заказы", callback_data="client_my_orders")],
            [InlineKeyboardButton("⬅️ В меню", callback_data="show_client_menu")],
        ]

        await message.reply_text(
            "🎉 <b>Заказ опубликован!</b>\n\n"
            f"📍 Город: {context.user_data['order_city']}\n"
            f"🔧 Категории: {categories_text}\n"
            f"📸 Фото: {photos_count}\n"
            f"📝 Описание: {context.user_data['order_description'][:50]}...\n\n"
            "Мастера получили уведомления о вашем заказе и скоро начнут откликаться!\n"
            "Вы сможете выбрать лучшего!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logger.info("✅ Сообщение отправлено клиенту")
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка создания заказа: {e}", exc_info=True)
        
        keyboard = [[InlineKeyboardButton("⬅️ В меню", callback_data="show_client_menu")]]
        
        await message.reply_text(
            f"❌ Ошибка при создании заказа:\n{str(e)}\n\nПопробуйте ещё раз или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data.clear()
        return ConversationHandler.END


# ============================================
# ЗАВЕРШЕНИЕ ЗАКАЗА И СИСТЕМА ОТЗЫВОВ
# ============================================

async def client_complete_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Клиент подтверждает завершение заказа"""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.replace("complete_order_", ""))

    # Помечаем что клиент подтвердил завершение
    both_confirmed = db.mark_order_completed_by_client(order_id)

    if both_confirmed:
        # Обе стороны подтвердили - заказ завершен
        order = db.get_order_by_id(order_id)
        worker_info = db.get_worker_info_for_order(order_id)

        if order and worker_info:
            order_dict = dict(order)
            worker_dict = dict(worker_info)

            # Уведомляем клиента
            await query.edit_message_text(
                "✅ <b>Заказ завершен!</b>\n\n"
                "Спасибо за подтверждение! Мастер также подтвердил завершение работы.\n\n"
                "Оставьте отзыв о работе мастера, это поможет другим заказчикам!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⭐ Оставить отзыв", callback_data=f"leave_review_{order_id}")
                ]])
            )

            # Уведомляем мастера
            user_id = worker_dict['user_id']
            user = db.get_user_by_id(user_id)
            if user:
                user_dict = dict(user)
                telegram_id = user_dict['telegram_id']
                try:
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text=f"✅ <b>Заказ #{order_id} завершен!</b>\n\n"
                             f"Клиент подтвердил завершение работы.\n"
                             f"Оставьте отзыв о работе с клиентом!",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⭐ Оставить отзыв", callback_data=f"leave_review_{order_id}")
                        ]])
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление мастеру: {e}")
    else:
        # Только клиент подтвердил, ждем мастера
        await query.edit_message_text(
            "✅ <b>Спасибо за подтверждение!</b>\n\n"
            "Ожидаем подтверждения от мастера.\n"
            "Когда обе стороны подтвердят завершение, вы сможете оставить отзыв.",
            parse_mode="HTML"
        )


async def worker_complete_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мастер подтверждает завершение заказа"""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.replace("worker_complete_order_", ""))

    # Помечаем что мастер подтвердил завершение
    both_confirmed = db.mark_order_completed_by_worker(order_id)

    if both_confirmed:
        # Обе стороны подтвердили - заказ завершен
        order = db.get_order_by_id(order_id)

        if order:
            order_dict = dict(order)

            # Уведомляем мастера
            await query.edit_message_text(
                "✅ <b>Заказ завершен!</b>\n\n"
                "Спасибо за подтверждение! Клиент также подтвердил завершение заказа.\n\n"
                "Оставьте отзыв о работе с клиентом!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⭐ Оставить отзыв", callback_data=f"leave_review_{order_id}")
                ]])
            )

            # Уведомляем клиента
            client_user_id = order_dict['client_user_id']
            user = db.get_user_by_id(client_user_id)
            if user:
                user_dict = dict(user)
                telegram_id = user_dict['telegram_id']
                try:
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text=f"✅ <b>Заказ #{order_id} завершен!</b>\n\n"
                             f"Мастер подтвердил завершение работы.\n"
                             f"Оставьте отзыв о работе мастера!",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⭐ Оставить отзыв", callback_data=f"leave_review_{order_id}")
                        ]])
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление клиенту: {e}")
    else:
        # Только мастер подтвердил, ждем клиента
        await query.edit_message_text(
            "✅ <b>Спасибо за подтверждение!</b>\n\n"
            "Ожидаем подтверждения от клиента.\n"
            "Когда обе стороны подтвердят завершение, вы сможете оставить отзыв.",
            parse_mode="HTML"
        )


async def start_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса оставления отзыва"""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.replace("leave_review_", ""))
    user_telegram_id = update.effective_user.id
    user = db.get_user(user_telegram_id)

    if not user:
        await query.edit_message_text("❌ Ошибка: пользователь не найден")
        return ConversationHandler.END

    user_dict = dict(user)
    user_id = user_dict['id']

    # Проверяем не оставлен ли уже отзыв
    if db.check_review_exists(order_id, user_id):
        await query.edit_message_text(
            "ℹ️ Вы уже оставили отзыв по этому заказу.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="start")
            ]])
        )
        return ConversationHandler.END

    # Получаем информацию о заказе
    order = db.get_order_by_id(order_id)
    if not order:
        await query.edit_message_text("❌ Заказ не найден")
        return ConversationHandler.END

    order_dict = dict(order)

    # Сохраняем информацию в контексте
    context.user_data['review_order_id'] = order_id
    context.user_data['review_from_user_id'] = user_id

    # Определяем кого оцениваем (клиент или мастер)
    client_user_id = order_dict['client_user_id']
    worker_info = db.get_worker_info_for_order(order_id)

    if user_id == client_user_id:
        # Клиент оценивает мастера
        if worker_info:
            worker_dict = dict(worker_info)
            context.user_data['review_to_user_id'] = worker_dict['user_id']
            context.user_data['review_role_from'] = 'client'
            context.user_data['review_role_to'] = 'worker'
            reviewer_name = worker_dict['name']
        else:
            await query.edit_message_text("❌ Информация о мастере не найдена")
            return ConversationHandler.END
    else:
        # Мастер оценивает клиента
        context.user_data['review_to_user_id'] = client_user_id
        context.user_data['review_role_from'] = 'worker'
        context.user_data['review_role_to'] = 'client'
        reviewer_name = order_dict['client_name']

    # Показываем выбор звезд
    keyboard = [
        [
            InlineKeyboardButton("⭐", callback_data="review_rating_1"),
            InlineKeyboardButton("⭐⭐", callback_data="review_rating_2"),
            InlineKeyboardButton("⭐⭐⭐", callback_data="review_rating_3"),
        ],
        [
            InlineKeyboardButton("⭐⭐⭐⭐", callback_data="review_rating_4"),
            InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="review_rating_5"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_review")]
    ]

    await query.edit_message_text(
        f"⭐ <b>Оставьте отзыв</b>\n\n"
        f"Оцените работу: <b>{reviewer_name}</b>\n\n"
        f"Выберите оценку от 1 до 5 звезд:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return REVIEW_SELECT_RATING


async def review_select_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора оценки"""
    query = update.callback_query
    await query.answer()

    rating = int(query.data.replace("review_rating_", ""))
    context.user_data['review_rating'] = rating

    # Просим написать комментарий
    keyboard = [[InlineKeyboardButton("⏭ Пропустить комментарий", callback_data="review_skip_comment")]]

    stars = "⭐" * rating
    await query.edit_message_text(
        f"✅ Оценка: {stars} ({rating}/5)\n\n"
        f"📝 Теперь напишите отзыв:\n"
        f"• Что понравилось или не понравилось?\n"
        f"• Качество работы\n"
        f"• Соблюдение сроков\n"
        f"• Коммуникация\n\n"
        f"Или пропустите, если хотите оставить только оценку.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return REVIEW_ENTER_COMMENT


async def review_enter_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текста отзыва"""
    comment = update.message.text.strip()

    if len(comment) > 1000:
        await update.message.reply_text(
            "❌ Отзыв слишком длинный. Максимум 1000 символов.\n"
            "Пожалуйста, сократите текст и отправьте снова."
        )
        return REVIEW_ENTER_COMMENT

    context.user_data['review_comment'] = comment

    # Сохраняем отзыв
    return await save_review(update, context)


async def review_skip_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск комментария - только оценка"""
    query = update.callback_query
    await query.answer()

    context.user_data['review_comment'] = ""

    # Сохраняем отзыв
    return await save_review(update, context, query=query)


async def save_review(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """Сохранение отзыва в базу данных"""
    try:
        from_user_id = context.user_data['review_from_user_id']
        to_user_id = context.user_data['review_to_user_id']
        order_id = context.user_data['review_order_id']
        role_from = context.user_data['review_role_from']
        role_to = context.user_data['review_role_to']
        rating = context.user_data['review_rating']
        comment = context.user_data.get('review_comment', '')

        # Сохраняем отзыв
        success = db.add_review(from_user_id, to_user_id, order_id, role_from, role_to, rating, comment)

        if success:
            stars = "⭐" * rating
            message_text = (
                f"✅ <b>Отзыв успешно опубликован!</b>\n\n"
                f"Оценка: {stars} ({rating}/5)\n"
            )
            if comment:
                message_text += f"\n📝 Комментарий:\n{comment[:100]}{'...' if len(comment) > 100 else ''}"

            keyboard = [[InlineKeyboardButton("⬅️ В главное меню", callback_data="start")]]

            if query:
                await query.edit_message_text(
                    message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            error_message = "❌ Не удалось сохранить отзыв. Возможно вы уже оставляли отзыв по этому заказу."
            if query:
                await query.edit_message_text(error_message)
            else:
                await update.message.reply_text(error_message)

    except Exception as e:
        logger.error(f"Ошибка при сохранении отзыва: {e}", exc_info=True)
        error_message = f"❌ Произошла ошибка при сохранении отзыва: {str(e)}"
        if query:
            await query.edit_message_text(error_message)
        else:
            await update.message.reply_text(error_message)

    # Очищаем данные
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена оставления отзыва"""
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "❌ Отмена. Вы можете оставить отзыв позже.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ В главное меню", callback_data="start")
        ]])
    )

    return ConversationHandler.END


async def show_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все отзывы о пользователе"""
    query = update.callback_query
    await query.answer()

    # Извлекаем user_id из callback_data (формат: show_reviews_worker_123 или show_reviews_client_123)
    parts = query.data.split("_")
    role = parts[2]  # worker или client
    profile_user_id = int(parts[3])

    # Получаем отзывы
    reviews = db.get_reviews_for_user(profile_user_id, role)

    if not reviews:
        await query.edit_message_text(
            "📊 <b>Отзывы</b>\n\n"
            "Пока нет отзывов.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=f"show_{role}_profile_{profile_user_id}")
            ]])
        )
        return

    # Формируем текст с отзывами
    message_text = "📊 <b>Отзывы</b>\n\n"

    for review in reviews[:10]:  # Показываем первые 10 отзывов
        review_dict = dict(review)
        rating = review_dict['rating']
        stars = "⭐" * rating
        reviewer_name = review_dict.get('reviewer_name', 'Аноним')
        comment = review_dict.get('comment', '')

        message_text += f"👤 <b>{reviewer_name}</b>\n"
        message_text += f"{stars} ({rating}/5)\n"
        if comment:
            # Обрезаем длинные комментарии
            if len(comment) > 150:
                comment = comment[:150] + "..."
            message_text += f"💬 {comment}\n"
        message_text += "\n"

    if len(reviews) > 10:
        message_text += f"<i>Показано 10 из {len(reviews)} отзывов</i>\n"

    await query.edit_message_text(
        message_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data=f"show_{role}_profile_{profile_user_id}")
        ]])
    )


# ============================================
# КОНЕЦ СИСТЕМЫ ОТЗЫВОВ
# ============================================


# ============================================
# СИСТЕМА УВЕДОМЛЕНИЙ (ANNOUNCE)
# ============================================

# ===== NOTIFICATION HELPERS =====

async def notify_worker_new_order(context, worker_telegram_id, order_dict):
    """Уведомление мастеру о новом заказе в его категории"""
    try:
        text = (
            f"🔔 <b>Новый заказ!</b>\n\n"
            f"📍 Город: {order_dict.get('city', 'Не указан')}\n"
            f"🔧 Категория: {order_dict.get('category', 'Не указана')}\n\n"
            f"📝 <b>Описание:</b>\n{order_dict.get('description', 'Без описания')}\n\n"
            f"💡 Перейдите в раздел «Доступные заказы», чтобы откликнуться!"
        )

        await context.bot.send_message(
            chat_id=worker_telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления мастеру {worker_telegram_id}: {e}")
        return False


async def notify_client_new_bid(context, client_telegram_id, order_id, worker_name, price, currency):
    """Уведомление клиенту о новом отклике на его заказ"""
    try:
        text = (
            f"🔔 <b>Новый отклик на ваш заказ #{order_id}!</b>\n\n"
            f"👤 Мастер: {worker_name}\n"
            f"💰 Предложенная цена: {price} {currency}\n\n"
            f"💡 Посмотрите все отклики в разделе «Мои заказы»"
        )

        await context.bot.send_message(
            chat_id=client_telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления клиенту {client_telegram_id}: {e}")
        return False


async def notify_worker_selected(context, worker_telegram_id, order_id, client_name, client_phone):
    """Уведомление мастеру что его выбрали для заказа"""
    try:
        text = (
            f"🎉 <b>Вас выбрали!</b>\n\n"
            f"Клиент выбрал вас для выполнения заказа #{order_id}\n\n"
            f"📞 <b>Контакт клиента:</b>\n"
            f"Имя: {client_name}\n"
            f"Телефон: <code>{client_phone}</code>\n\n"
            f"✅ Свяжитесь с клиентом и обсудите детали заказа!\n\n"
            f"💡 После завершения работы не забудьте отметить заказ как выполненный."
        )

        await context.bot.send_message(
            chat_id=worker_telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления мастеру {worker_telegram_id}: {e}")
        return False


async def notify_client_master_selected(context, client_telegram_id, order_id, worker_name, worker_phone):
    """Уведомление клиенту что он успешно выбрал мастера"""
    try:
        text = (
            f"✅ <b>Мастер выбран!</b>\n\n"
            f"Вы выбрали мастера для заказа #{order_id}\n\n"
            f"👤 <b>Контакт мастера:</b>\n"
            f"Имя: {worker_name}\n"
            f"Телефон: <code>{worker_phone}</code>\n\n"
            f"✅ Свяжитесь с мастером и обсудите детали заказа!\n\n"
            f"💡 После завершения работы не забудьте отметить заказ как выполненный и оставить отзыв."
        )

        await context.bot.send_message(
            chat_id=client_telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления клиенту {client_telegram_id}: {e}")
        return False


async def notify_completion_request(context, recipient_telegram_id, order_id, requester_role):
    """Уведомление о том что другая сторона отметила заказ как завершённый"""
    role_text = "Клиент" if requester_role == "client" else "Мастер"

    try:
        text = (
            f"✅ <b>Запрос на завершение заказа #{order_id}</b>\n\n"
            f"{role_text} отметил заказ как выполненный.\n\n"
            f"Если работа действительно завершена, подтвердите завершение в разделе «Мои заказы».\n\n"
            f"💡 После подтверждения обеих сторон вы сможете оставить отзыв."
        )

        await context.bot.send_message(
            chat_id=recipient_telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления {recipient_telegram_id}: {e}")
        return False


async def notify_order_completed(context, telegram_id, order_id, role):
    """Уведомление об успешном завершении заказа"""
    try:
        text = (
            f"🎉 <b>Заказ #{order_id} завершён!</b>\n\n"
            f"Обе стороны подтвердили завершение заказа.\n\n"
            f"💬 Не забудьте оставить отзыв о {'мастере' if role == 'client' else 'клиенте'}!\n\n"
            f"Это поможет другим пользователям сделать правильный выбор. 🤝"
        )

        await context.bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления {telegram_id}: {e}")
        return False


async def notify_new_review(context, telegram_id, reviewer_name, rating, order_id):
    """Уведомление о получении нового отзыва"""
    stars = "⭐" * int(rating)

    try:
        text = (
            f"📝 <b>Новый отзыв!</b>\n\n"
            f"👤 От: {reviewer_name}\n"
            f"{stars} {rating}/5\n"
            f"📋 Заказ: #{order_id}\n\n"
            f"Посмотрите отзыв в своём профиле!"
        )

        await context.bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления {telegram_id}: {e}")
        return False


async def enable_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /enable_premium для включения premium функций
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    ADMIN_IDS = [user_telegram_id]  # По умолчанию только создатель команды

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    # Включаем premium функции
    db.set_premium_enabled(True)

    await update.message.reply_text(
        "✅ <b>Premium функции включены!</b>\n\n"
        "Теперь доступны:\n"
        "• Поднятие заказов в топ\n"
        "• Premium профили мастеров\n"
        "• Выделение в списках\n\n"
        "💡 Используйте /disable_premium для отключения",
        parse_mode="HTML"
    )


async def disable_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /disable_premium для отключения premium функций
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    ADMIN_IDS = [user_telegram_id]  # По умолчанию только создатель команды

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    # Выключаем premium функции
    db.set_premium_enabled(False)

    await update.message.reply_text(
        "✅ <b>Premium функции отключены!</b>\n\n"
        "Все premium возможности скрыты от пользователей.\n\n"
        "💡 Используйте /enable_premium для включения",
        parse_mode="HTML"
    )


async def premium_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /premium_status для проверки статуса premium функций
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    ADMIN_IDS = [user_telegram_id]  # По умолчанию только создатель команды

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    is_enabled = db.is_premium_enabled()

    status_emoji = "✅" if is_enabled else "❌"
    status_text = "Включены" if is_enabled else "Отключены"

    await update.message.reply_text(
        f"📊 <b>Статус Premium функций</b>\n\n"
        f"{status_emoji} Статус: <b>{status_text}</b>\n\n"
        f"<b>Доступные команды:</b>\n"
        f"/enable_premium - Включить premium\n"
        f"/disable_premium - Отключить premium\n"
        f"/premium_status - Проверить статус",
        parse_mode="HTML"
    )


async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /ban для блокировки пользователя
    Использование: /ban telegram_id причина
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    ADMIN_IDS = [user_telegram_id]

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 <b>Использование команды /ban</b>\n\n"
            "<code>/ban telegram_id причина</code>\n\n"
            "Пример:\n"
            "<code>/ban 123456789 Спам</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_telegram_id = int(context.args[0])
        reason = " ".join(context.args[1:])

        # Проверяем существование пользователя
        user = db.get_user(target_telegram_id)
        if not user:
            await update.message.reply_text(
                f"❌ Пользователь с ID {target_telegram_id} не найден в базе."
            )
            return

        # Нельзя забанить самого себя или другого админа
        if target_telegram_id in ADMIN_IDS:
            await update.message.reply_text("❌ Нельзя забанить администратора.")
            return

        # Баним пользователя
        success = db.ban_user(target_telegram_id, reason, str(user_telegram_id))

        if success:
            await update.message.reply_text(
                f"✅ <b>Пользователь забанен</b>\n\n"
                f"ID: <code>{target_telegram_id}</code>\n"
                f"Причина: {reason}\n\n"
                f"Пользователь больше не сможет использовать бота.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("❌ Ошибка при блокировке пользователя.")

    except ValueError:
        await update.message.reply_text("❌ Неверный формат Telegram ID. Используйте числовой ID.")
    except Exception as e:
        logger.error(f"Ошибка в ban_user_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /unban для разблокировки пользователя
    Использование: /unban telegram_id
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    ADMIN_IDS = [user_telegram_id]

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "📋 <b>Использование команды /unban</b>\n\n"
            "<code>/unban telegram_id</code>\n\n"
            "Пример:\n"
            "<code>/unban 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_telegram_id = int(context.args[0])

        # Разбаниваем пользователя
        success = db.unban_user(target_telegram_id)

        if success:
            await update.message.reply_text(
                f"✅ <b>Пользователь разблокирован</b>\n\n"
                f"ID: <code>{target_telegram_id}</code>\n\n"
                f"Пользователь снова может использовать бота.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"❌ Пользователь с ID {target_telegram_id} не найден или не был забанен."
            )

    except ValueError:
        await update.message.reply_text("❌ Неверный формат Telegram ID. Используйте числовой ID.")
    except Exception as e:
        logger.error(f"Ошибка в unban_user_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def banned_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /banned для просмотра списка забаненных пользователей
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    ADMIN_IDS = [user_telegram_id]

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    banned_users = db.get_banned_users()

    if not banned_users:
        await update.message.reply_text("📋 Список забаненных пользователей пуст.")
        return

    text = "🚫 <b>Забаненные пользователи</b>\n\n"

    for user in banned_users[:10]:  # Показываем первых 10
        telegram_id = user[0]
        reason = user[1] or "Не указана"
        banned_at = user[2] or "Неизвестно"
        banned_by = user[3] or "Неизвестно"

        text += (
            f"👤 ID: <code>{telegram_id}</code>\n"
            f"📝 Причина: {reason}\n"
            f"📅 Дата: {banned_at}\n"
            f"👮 Забанил: {banned_by}\n\n"
        )

    text += f"\n<i>Всего забанено: {len(banned_users)}</i>"

    await update.message.reply_text(text, parse_mode="HTML")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /stats для просмотра статистики бота
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    ADMIN_IDS = [user_telegram_id]

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    stats = db.get_analytics_stats()

    premium_status = "✅ Включены" if stats['premium_enabled'] else "❌ Отключены"

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"• Всего: {stats['total_users']}\n"
        f"• Мастеров: {stats['total_workers']}\n"
        f"• Клиентов: {stats['total_clients']}\n"
        f"• Забанено: {stats['banned_users']}\n\n"
        f"📋 <b>Заказы:</b>\n"
        f"• Всего: {stats['total_orders']}\n"
        f"• Активных: {stats['active_orders']}\n"
        f"• Завершённых: {stats['completed_orders']}\n\n"
        f"💼 <b>Отклики:</b>\n"
        f"• Всего: {stats['total_bids']}\n"
        f"• Активных: {stats['active_bids']}\n\n"
        f"⭐ <b>Отзывы:</b> {stats['total_reviews']}\n\n"
        f"💎 <b>Premium:</b> {premium_status}"
    )

    await update.message.reply_text(text, parse_mode="HTML")


async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /announce для отправки уведомлений всем пользователям.
    Использование: /announce Текст сообщения
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора (можно заменить на список админов)
    ADMIN_IDS = [user_telegram_id]  # По умолчанию только создатель команды

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    # Извлекаем текст сообщения
    if not context.args:
        await update.message.reply_text(
            "📢 <b>Команда /announce</b>\n\n"
            "Использование:\n"
            "<code>/announce Текст уведомления</code>\n\n"
            "Пример:\n"
            "<code>/announce ⚠️ Завтра с 10:00 до 12:00 технические работы. Бот будет недоступен.</code>",
            parse_mode="HTML"
        )
        return

    message_text = " ".join(context.args)

    # Получаем всех пользователей
    telegram_ids = db.get_all_user_telegram_ids()

    if not telegram_ids:
        await update.message.reply_text("ℹ️ В базе нет пользователей для рассылки.")
        return

    # Отправляем уведомление
    await update.message.reply_text(
        f"📤 Начинаю рассылку {len(telegram_ids)} пользователям...\n"
        f"Текст:\n<i>{message_text}</i>",
        parse_mode="HTML"
    )

    sent_count = 0
    failed_count = 0

    for telegram_id in telegram_ids:
        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=f"📢 <b>Уведомление от администрации</b>\n\n{message_text}",
                parse_mode="HTML"
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {telegram_id}: {e}")
            failed_count += 1

    # Отчет о рассылке
    await update.message.reply_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"✅ Отправлено: {sent_count}\n"
        f"❌ Не удалось: {failed_count}\n"
        f"📊 Всего: {len(telegram_ids)}",
        parse_mode="HTML"
    )


async def check_expired_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /check_expired_chats для проверки и обработки чатов где мастер не ответил в течение 24 часов.
    Эта команда также может быть запущена автоматически по расписанию (cron/scheduler).
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора (можно заменить на список админов)
    ADMIN_IDS = [user_telegram_id]  # По умолчанию только создатель команды

    if user_telegram_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return

    # Получаем все просроченные чаты (где мастер не ответил в течение 24 часов)
    expired_chats = db.get_expired_chats(hours=24)

    if not expired_chats:
        await update.message.reply_text("✅ Нет просроченных чатов (все мастера отвечают вовремя).")
        return

    await update.message.reply_text(
        f"🔍 Найдено просроченных чатов: {len(expired_chats)}\n"
        f"Начинаю обработку...",
        parse_mode="HTML"
    )

    processed_count = 0
    error_count = 0

    for chat in expired_chats:
        try:
            chat_id = chat['id']
            order_id = chat['order_id']
            client_user_id = chat['client_user_id']
            worker_user_id = chat['worker_user_id']
            bid_id = chat['bid_id']

            # Получаем информацию о заказе
            order = db.get_order_by_id(order_id)
            if not order:
                logger.warning(f"Заказ {order_id} не найден для чата {chat_id}")
                error_count += 1
                continue

            # Получаем информацию о клиенте и мастере
            client = db.get_user_by_id(client_user_id)
            worker_user = db.get_user_by_id(worker_user_id)

            if not client or not worker_user:
                logger.warning(f"Пользователи не найдены для чата {chat_id}")
                error_count += 1
                continue

            # 1. Снижаем рейтинг мастера (добавляем негативную оценку 1.0 из 5.0)
            db.update_user_rating(worker_user_id, 1.0, "worker")

            # 2. Возвращаем заказ в статус "open" (клиент может выбрать другого мастера)
            db.update_order_status(order_id, "open")

            # 3. Отмечаем отклик как отклоненный (чтобы не показывался как выбранный)
            # Но НЕ удаляем его - клиент может увидеть, что этот мастер не ответил
            db.update_bid_status(bid_id, "rejected")

            # 4. Уведомляем клиента что мастер не ответил и он может выбрать другого БЕЗ доп. оплаты
            try:
                await context.bot.send_message(
                    chat_id=client['telegram_id'],
                    text=(
                        f"⚠️ <b>Мастер не ответил в течение 24 часов</b>\n\n"
                        f"📋 Заказ: {order['title']}\n\n"
                        f"Ваш заказ снова открыт для выбора другого мастера.\n"
                        f"💰 Дополнительная оплата НЕ требуется - ваша предыдущая оплата остается активной.\n\n"
                        f"Просто выберите другого мастера из списка откликов."
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")
                    ]])
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление клиенту {client['telegram_id']}: {e}")

            # 5. Уведомляем мастера о снижении рейтинга
            try:
                await context.bot.send_message(
                    chat_id=worker_user['telegram_id'],
                    text=(
                        f"⚠️ <b>Ваш рейтинг снижен!</b>\n\n"
                        f"📋 Заказ: {order['title']}\n\n"
                        f"Вы не ответили клиенту в течение 24 часов после того, как ваш отклик был выбран.\n"
                        f"📉 Ваш рейтинг был снижен.\n\n"
                        f"⚡ <b>Совет:</b> Отвечайте клиентам быстрее, чтобы поддерживать высокий рейтинг!"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление мастеру {worker_user['telegram_id']}: {e}")

            processed_count += 1
            logger.info(f"Обработан просроченный чат {chat_id} (заказ {order_id})")

        except Exception as e:
            logger.error(f"Ошибка при обработке чата {chat.get('id', 'unknown')}: {e}")
            error_count += 1

    # Отчет о проверке
    await update.message.reply_text(
        f"✅ <b>Проверка завершена!</b>\n\n"
        f"✅ Обработано: {processed_count}\n"
        f"❌ Ошибок: {error_count}\n"
        f"📊 Всего найдено: {len(expired_chats)}",
        parse_mode="HTML"
    )


# ============================================
# КОНЕЦ СИСТЕМЫ УВЕДОМЛЕНИЙ
# ============================================
