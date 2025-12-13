import logging
import re
import asyncio
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
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


# ===== BELARUS REGIONS AND CITIES =====

BELARUS_REGIONS = {
    "Минск": {
        "type": "city",  # Минск - отдельный город, не часть Минской области
        "display": "🏛 Минск"
    },
    "Брестская область": {
        "type": "region",
        "display": "🌾 Брестская область",
        "cities": ["Брест", "Барановичи", "Пинск", "Кобрин", "Лунинец"]
    },
    "Витебская область": {
        "type": "region",
        "display": "🌲 Витебская область",
        "cities": ["Витебск", "Полоцк", "Новополоцк", "Орша", "Глубокое"]
    },
    "Гомельская область": {
        "type": "region",
        "display": "🏭 Гомельская область",
        "cities": ["Гомель", "Мозырь", "Жлобин", "Светлогорск", "Речица"]
    },
    "Гродненская область": {
        "type": "region",
        "display": "🏰 Гродненская область",
        "cities": ["Гродно", "Лида", "Слоним", "Волковыск", "Сморгонь"]
    },
    "Минская область": {
        "type": "region",
        "display": "🌳 Минская область",
        "cities": ["Солигорск", "Борисов", "Молодечно", "Жодино", "Слуцк"]
    },
    "Могилёвская область": {
        "type": "region",
        "display": "🌾 Могилёвская область",
        "cities": ["Могилёв", "Бобруйск", "Осиповичи", "Горки", "Кричев"]
    },
    "Вся Беларусь": {
        "type": "country",
        "display": "🇧🇾 Вся Беларусь"
    }
}


# ===== WORK CATEGORIES HIERARCHY =====

WORK_CATEGORIES = {
    "inner": {
        "name": "🧱 Внутренние работы",
        "emoji": "🧱",
        "subcategories": [
            "Электрика",
            "Сантехника",
            "Отопление",
            "Малярные работы",
            "Штукатурные работы",
            "Плиточные работы",
            "Полы",
            "Потолки",
            "Стены и перегородки",
            "Окна и двери (внутренняя установка)"
        ]
    },
    "outer": {
        "name": "🏠 Наружные работы",
        "emoji": "🏠",
        "subcategories": [
            "Кровля",
            "Фасад",
            "Фундамент",
            "Заборы и ворота",
            "Тротуарная плитка",
            "Бетонные работы",
            "Сварочные работы",
            "Деревянные конструкции"
        ]
    },
    "design": {
        "name": "🔧 Отделка и дизайн",
        "emoji": "🔧",
        "subcategories": [
            "Дизайн интерьера",
            "Декор",
            "Мебель на заказ",
            "Установка бытовой техники",
            "Уборка после ремонта"
        ]
    },
    "landscape": {
        "name": "🌳 Благоустройство и участок",
        "emoji": "🌳",
        "subcategories": [
            "Ландшафтные работы",
            "Асфальтирование",
            "Заборы, ворота",
            "Септики, канализация, дренаж",
            "Снегоуборка"
        ]
    },
    "engineering": {
        "name": "🧰 Специализированные и инженерные системы",
        "emoji": "🧰",
        "subcategories": [
            "Системы вентиляции",
            "Кондиционирование",
            "Слаботочные системы",
            "Умный дом"
        ]
    },
    "demolition": {
        "name": "⚙️ Демонтаж и черновые работы",
        "emoji": "⚙️",
        "subcategories": [
            "Снос перегородок",
            "Демонтаж плитки, полов, потолков",
            "Вывоз строительного мусора",
            "Черновая подготовка"
        ]
    },
    "other": {
        "name": "💡 Прочие услуги",
        "emoji": "💡",
        "subcategories": [
            "Курьерские, подсобные, грузчики",
            "Сборка мебели",
            "Мелкий бытовой ремонт",
            "Услуги по дому (мелкие заявки)"
        ]
    }
}


# ===== HELPER FUNCTIONS =====

async def safe_edit_message(query, text, **kwargs):
    """
    КРИТИЧЕСКИ ВАЖНО: Безопасное редактирование сообщения.

    Обрабатывает:
    - Timeout callback_query (>30 сек)
    - Попытка редактировать одинаковый текст
    - Другие BadRequest ошибки

    Если редактирование невозможно, отправляет новое сообщение.
    """
    import telegram

    try:
        await query.edit_message_text(text, **kwargs)
    except telegram.error.BadRequest as e:
        error_msg = str(e).lower()

        if "message is not modified" in error_msg:
            # Текст не изменился, ничего не делаем
            logger.debug("Message not modified, skipping")
            return

        if "query is too old" in error_msg or "message can't be edited" in error_msg:
            # Callback устарел (>30 сек), отправляем новое сообщение
            logger.warning("Callback query too old, sending new message")
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception as send_error:
                logger.error(f"Failed to send new message: {send_error}")
        else:
            # Другая BadRequest ошибка, логируем и пробрасываем
            logger.error(f"BadRequest in edit_message: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error in safe_edit_message: {e}", exc_info=True)
        raise


def safe_get_user_data(context, keys, default=None):
    """
    КРИТИЧЕСКИ ВАЖНО: Безопасное получение данных из context.user_data.

    Args:
        context: Telegram context
        keys: str или list - ключ или список ключей для проверки
        default: значение по умолчанию если ключа нет

    Returns:
        dict: {key: value} или {key: default} для каждого ключа

    Пример:
        data = safe_get_user_data(context, ["name", "phone", "city"])
        if None in data.values():
            # Не хватает данных
            return error_message
    """
    if isinstance(keys, str):
        keys = [keys]

    result = {}
    for key in keys:
        result[key] = context.user_data.get(key, default)

    return result


def validate_required_fields(context, required_fields):
    """
    КРИТИЧЕСКИ ВАЖНО: Проверяет наличие обязательных полей в context.user_data.

    Args:
        context: Telegram context
        required_fields: list - список обязательных ключей

    Returns:
        tuple: (bool, list) - (все ли есть, список отсутствующих)

    Пример:
        ok, missing = validate_required_fields(context, ["name", "phone"])
        if not ok:
            logger.error(f"Missing fields: {missing}")
            return error
    """
    missing = [f for f in required_fields if f not in context.user_data]
    return (len(missing) == 0, missing)


def validate_file_id(file_id):
    """
    КРИТИЧЕСКИ ВАЖНО: Валидация file_id от Telegram.

    Telegram file_id - это строка длиной 50-200 символов, содержащая:
    - Буквы (A-Z, a-z)
    - Цифры (0-9)
    - Спецсимволы: _ - =

    Args:
        file_id: строка с file_id для проверки

    Returns:
        bool: True если file_id валиден, False иначе

    Примеры:
        ✅ "AgACAgIAAxkBAAIBY2..."  # валидный
        ❌ ""                       # пустой
        ❌ None                     # не строка
        ❌ "abc"                    # слишком короткий
        ❌ "abc<script>"            # недопустимые символы
    """
    if not file_id or not isinstance(file_id, str):
        logger.warning(f"❌ file_id невалиден: пустой или не строка ({type(file_id)})")
        return False

    # Проверка длины (Telegram file_id обычно 50-200 символов)
    if len(file_id) < 20 or len(file_id) > 250:
        logger.warning(f"❌ file_id невалиден: неправильная длина ({len(file_id)} символов)")
        return False

    # Проверка разрешенных символов (только безопасные для Telegram)
    if not re.match(r'^[A-Za-z0-9_\-=]+$', file_id):
        logger.warning(f"❌ file_id невалиден: недопустимые символы")
        return False

    return True


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
    REGISTER_MASTER_REGION_SELECT,
    REGISTER_MASTER_CITY,
    REGISTER_MASTER_CITY_SELECT,
    REGISTER_MASTER_CITY_OTHER,
    REGISTER_MASTER_MAIN_CATEGORY,
    REGISTER_MASTER_SUBCATEGORY_SELECT,
    REGISTER_MASTER_ASK_MORE_CATEGORIES,
    REGISTER_MASTER_EXPERIENCE,
    REGISTER_MASTER_DESCRIPTION,
    REGISTER_MASTER_PHOTOS,
    REGISTER_CLIENT_NAME,
    REGISTER_CLIENT_PHONE,
    REGISTER_CLIENT_REGION_SELECT,
    REGISTER_CLIENT_CITY,
    REGISTER_CLIENT_CITY_SELECT,
    REGISTER_CLIENT_CITY_OTHER,
    REGISTER_CLIENT_DESCRIPTION,
    # Новые состояния для редактирования профиля
    EDIT_PROFILE_MENU,
    EDIT_NAME,
    EDIT_PHONE,
    EDIT_REGION_SELECT,
    EDIT_CITY,
    EDIT_MAIN_CATEGORY,
    EDIT_SUBCATEGORY_SELECT,
    EDIT_ASK_MORE_CATEGORIES,
    EDIT_EXPERIENCE,
    EDIT_DESCRIPTION,
    ADD_PHOTOS_MENU,
    ADD_PHOTOS_UPLOAD,
    # Состояния для создания заказа
    CREATE_ORDER_REGION_SELECT,
    CREATE_ORDER_CITY,
    CREATE_ORDER_MAIN_CATEGORY,
    CREATE_ORDER_SUBCATEGORY_SELECT,
    CREATE_ORDER_DESCRIPTION,
    CREATE_ORDER_PHOTOS,
    # Состояния для создания отклика
    BID_ENTER_PRICE,
    BID_SELECT_CURRENCY,
    BID_ENTER_COMMENT,
    # Состояния для оставления отзыва
    REVIEW_SELECT_RATING,
    REVIEW_ENTER_COMMENT,
) = range(43)


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
            "Нам нужно собрать некоторую информацию о вас, чтобы вы могли создать заказ.\n\n"
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
        "📱 Укажите номер телефона.\n"
        "Он необходим для регистрации и не будет виден всем подряд.\n\n"
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

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"masterregion_{region_name}"
        )])

    await update.message.reply_text(
        "🏙 <b>Где вы работаете?</b>\n\n"
        "Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REGISTER_MASTER_REGION_SELECT


async def register_master_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора региона мастером"""
    query = update.callback_query
    await query.answer()

    region = query.data.replace("masterregion_", "")
    region_data = BELARUS_REGIONS.get(region)

    if not region_data:
        await query.edit_message_text("❌ Ошибка выбора региона. Попробуйте снова.")
        return REGISTER_MASTER_REGION_SELECT

    context.user_data["region"] = region

    # Если выбран Минск или "Вся Беларусь" - сохраняем и переходим к выбору типа работ
    if region_data["type"] in ["city", "country"]:
        context.user_data["city"] = region
        context.user_data["regions"] = region

        # Переходим к выбору типа работ
        keyboard = [
            [InlineKeyboardButton(
                f"{WORK_CATEGORIES['Наружные работы']['emoji']} Наружные работы",
                callback_data="worktype_Наружные работы"
            )],
            [InlineKeyboardButton(
                f"{WORK_CATEGORIES['Внутренние работы']['emoji']} Внутренние работы",
                callback_data="worktype_Внутренние работы"
            )],
        ]

        await query.edit_message_text(
            f"📍 Регион: {region}\n\n"
            "🏗 <b>Выберите тип работ:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_MASTER_WORK_TYPE

    # Если выбрана область - показываем города
    else:
        cities = region_data.get("cities", [])
        keyboard = []
        row = []
        for city in cities:
            row.append(InlineKeyboardButton(city, callback_data=f"mastercity_{city}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:  # Добавляем оставшиеся города
            keyboard.append(row)

        # Добавляем кнопку "Другой город в области"
        keyboard.append([InlineKeyboardButton(
            f"📍 Другой город в области",
            callback_data="mastercity_other"
        )])

        await query.edit_message_text(
            f"🏙 Выберите город в регионе <b>{region}</b>:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REGISTER_MASTER_CITY_SELECT


async def register_master_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города мастером после выбора региона"""
    query = update.callback_query
    await query.answer()

    city = query.data.replace("mastercity_", "")

    if city == "other":
        region = context.user_data.get("region", "")
        await query.edit_message_text(
            f"🏙 Напишите название города в регионе <b>{region}</b>:",
            parse_mode="HTML"
        )
        return REGISTER_MASTER_CITY_OTHER
    else:
        context.user_data["city"] = city
        region = context.user_data.get("region", city)
        context.user_data["regions"] = region

        # Инициализируем список категорий если его нет
        if "categories" not in context.user_data:
            context.user_data["categories"] = []

        # Переходим к выбору основной категории
        keyboard = []
        for cat_id, category_data in WORK_CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(
                category_data["name"],
                callback_data=f"maincat_{cat_id}"
            )])

        await query.edit_message_text(
            f"🏙 Город: {city}\n\n"
            "🔧 <b>Шаг 4/7:</b> Выберите основную категорию работ:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_MASTER_MAIN_CATEGORY


async def register_master_city_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод другого города мастером вручную"""
    city = update.message.text.strip()
    context.user_data["city"] = city
    region = context.user_data.get("region", city)
    context.user_data["regions"] = region

    # Переходим к выбору основной категории
    # Инициализируем список категорий если его нет
    if "categories" not in context.user_data:
        context.user_data["categories"] = []

    keyboard = []
    for cat_id, category_data in WORK_CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(
                category_data["name"],
                callback_data=f"maincat_{cat_id}"
            )])

    await update.message.reply_text(
        f"🏙 Город: {city}\n\n"
        "🔧 <b>Шаг 4/7:</b> Выберите основную категорию работ:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return REGISTER_MASTER_MAIN_CATEGORY


async def register_master_main_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора основной категории работ"""
    query = update.callback_query
    await query.answer()

    cat_id = query.data.replace("maincat_", "")
    category_name = WORK_CATEGORIES[cat_id]["name"]
    context.user_data["current_main_category"] = cat_id

    # Получаем подкатегории для выбранной категории
    subcategories = WORK_CATEGORIES[cat_id]["subcategories"]

    # Создаем кнопки подкатегорий (2 в ряд) с галочками
    keyboard = []
    row = []
    for idx, subcat in enumerate(subcategories):
        # Проверяем выбрана ли уже эта подкатегория
        is_selected = subcat in context.user_data.get("categories", [])
        button_text = f"✅ {subcat}" if is_selected else subcat

        row.append(InlineKeyboardButton(button_text, callback_data=f"subcat_{cat_id}:{idx}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:  # Добавляем оставшуюся кнопку
        keyboard.append(row)

    # Добавляем кнопку завершения
    keyboard.append([InlineKeyboardButton("✅ Завершить выбор категорий", callback_data="subcat_done")])

    city = context.user_data.get("city", "")
    emoji = WORK_CATEGORIES[cat_id]["emoji"]

    await query.edit_message_text(
        f"🏙 Город: {city}\n"
        f"{emoji} <b>Категория:</b> {category_name}\n\n"
        "🔧 <b>Выберите подкатегории:</b>\n\n"
        "Нажимайте подходящие кнопки (можно несколько).\n"
        "Когда закончите — нажмите «✅ Завершить выбор категорий».",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return REGISTER_MASTER_SUBCATEGORY_SELECT


async def register_master_subcategory_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора подкатегорий с переключением галочек"""
    query = update.callback_query
    await query.answer()
    data = query.data
    selected = data.replace("subcat_", "")

    if selected == "done":
        # Проверяем что выбрана хотя бы одна подкатегория
        if not context.user_data.get("categories"):
            await query.answer("Выберите хотя бы одну подкатегорию!", show_alert=True)
            return REGISTER_MASTER_SUBCATEGORY_SELECT

        # Спрашиваем хочет ли добавить еще категории
        keyboard = [
            [InlineKeyboardButton("✅ Да, добавить еще", callback_data="more_yes")],
            [InlineKeyboardButton("➡️ Нет, продолжить дальше", callback_data="more_no")],
        ]

        categories_text = ", ".join(context.user_data["categories"])

        await query.edit_message_text(
            f"✅ <b>Выбранные категории:</b>\n{categories_text}\n\n"
            "Хотите добавить еще категории из других разделов?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_MASTER_ASK_MORE_CATEGORIES

    else:
        # Парсим cat_id:index из callback_data
        cat_id, idx_str = selected.split(":")
        idx = int(idx_str)
        subcat_name = WORK_CATEGORIES[cat_id]["subcategories"][idx]

        # Переключаем выбор подкатегории
        if "categories" not in context.user_data:
            context.user_data["categories"] = []

        if subcat_name not in context.user_data["categories"]:
            context.user_data["categories"].append(subcat_name)
            await query.answer(f"✅ Добавлено: {subcat_name}")
        else:
            context.user_data["categories"].remove(subcat_name)
            await query.answer(f"❌ Убрано: {subcat_name}")

        # Обновляем кнопки с галочками
        main_category = context.user_data["current_main_category"]
        subcategories = WORK_CATEGORIES[cat_id]["subcategories"]
        category_name = WORK_CATEGORIES[cat_id]["name"]

        keyboard = []
        row = []
        for idx2, subcat in enumerate(subcategories):
            is_selected = subcat in context.user_data["categories"]
            button_text = f"✅ {subcat}" if is_selected else subcat

            row.append(InlineKeyboardButton(button_text, callback_data=f"subcat_{cat_id}:{idx2}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("✅ Завершить выбор категорий", callback_data="subcat_done")])

        city = context.user_data.get("city", "")
        emoji = WORK_CATEGORIES[cat_id]["emoji"]

        await query.edit_message_text(
            f"🏙 Город: {city}\n"
            f"{emoji} <b>Категория:</b> {category_name}\n\n"
            "🔧 <b>Выберите подкатегории:</b>\n\n"
            "Нажимайте подходящие кнопки (можно несколько).\n"
            "Когда закончите — нажмите «✅ Завершить выбор категорий».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return REGISTER_MASTER_SUBCATEGORY_SELECT


async def register_master_ask_more_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Спрашиваем хочет ли мастер добавить еще категории"""
    query = update.callback_query
    await query.answer()

    choice = query.data.replace("more_", "")

    if choice == "yes":
        # Возвращаемся к выбору основной категории
        keyboard = []
        for cat_id, category_data in WORK_CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(
                category_data["name"],
                callback_data=f"maincat_{cat_id}"
            )])

        city = context.user_data.get("city", "")
        categories_text = ", ".join(context.user_data["categories"])

        await query.edit_message_text(
            f"🏙 Город: {city}\n\n"
            f"✅ <b>Уже выбрано:</b> {categories_text}\n\n"
            "🔧 <b>Выберите основную категорию для добавления:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_MASTER_MAIN_CATEGORY

    else:
        # Переходим к выбору уровня мастерства
        keyboard = [
            [InlineKeyboardButton("🌱 Начинающий мастер", callback_data="exp_Начинающий мастер")],
            [InlineKeyboardButton("⚡ Опытный мастер", callback_data="exp_Опытный мастер")],
            [InlineKeyboardButton("⭐ Профессионал", callback_data="exp_Профессионал")],
        ]

        categories_text = ", ".join(context.user_data["categories"])

        await query.edit_message_text(
            f"✅ <b>Выбранные категории:</b>\n{categories_text}\n\n"
            "📊 <b>Шаг 5/7:</b> Укажите ваш уровень мастерства:\n\n"
            "🌱 <b>Начинающий мастер</b> — осваиваете профессию, выполняете простые работы\n"
            "⚡ <b>Опытный мастер</b> — уверенно работаете, есть портфолио выполненных проектов\n"
            "⭐ <b>Профессионал</b> — высокий уровень, сложные проекты, большой опыт",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_MASTER_EXPERIENCE


async def register_master_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    experience = query.data.replace("exp_", "")
    context.user_data["experience"] = experience
    
    await query.edit_message_text(
        f"Уровень: {experience}\n\n"
        "📝 <b>Расскажите о своём опыте и выполненных проектах</b>\n\n"
        "💡 Это описание увидят потенциальные заказчики. Укажите:\n\n"
        "✓ <b>Опыт работы:</b> Сколько лет в профессии, какие объекты выполняли\n"
        "✓ <b>Примеры проектов:</b> Что делали, какой сложности работы\n"
        "✓ <b>Специализация:</b> В чём вы особенно сильны\n"
        "✓ <b>Как работаете:</b> Гарантия, свой инструмент, аккуратность, сроки\n\n"
        "<b>Пример:</b>\n"
        "«Занимаюсь электрикой 7 лет. Делал проводку в 50+ квартирах и 10 частных домах. "
        "Специализируюсь на сложных схемах освещения и умных домах. Работаю аккуратно, "
        "весь мусор убираю. Даю гарантию 2 года. Свой профессиональный инструмент.»",
        parse_mode="HTML"
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
        "📸 <b>Ваше портфолио (до 4 фотографий)</b>\n\n"
        "Добавьте фотографии, чтобы клиенты увидели качество ваших работ.\n\n"
        "⚠️ <b>ВАЖНО про первое фото:</b>\n"
        "🤵 Первая фотография должна быть <b>с вашим лицом</b>\n"
        "Это повышает доверие клиентов и показывает, что вы реальный мастер.\n\n"
        "📋 Дальше добавьте <b>до 3 фотографий ваших работ:</b>\n"
        "• Завершённые объекты\n"
        "• Процесс работы\n"
        "• Примеры сложных проектов\n\n"
        "💡 <i>Мастера с фото получают в 5 раз больше откликов!</i>",
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
            "📸 <b>Загрузка портфолио (до 4 фото)</b>\n\n"
            "🤵 <b>Фото #1 - Ваше лицо (обязательно!)</b>\n\n"
            "Отправьте фото, на котором вас хорошо видно.\n"
            "Это может быть:\n"
            "• Фото на рабочем месте\n"
            "• Фото с инструментом\n"
            "• Фото на объекте\n\n"
            "❗ Главное - чтобы было видно ваше лицо. Это повышает доверие клиентов.",
            parse_mode="HTML",
        )
        return REGISTER_MASTER_PHOTOS
    else:
        # Пропускаем фото, завершаем регистрацию
        return await finalize_master_registration(update, context)


async def handle_master_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загруженных фотографий"""
    logger.info(f"handle_master_photos вызван. Текст: {update.message.text if update.message.text else 'фото'}")

    # КРИТИЧНО: Проверка на видео/документы (не фото)
    if update.message.video:
        logger.warning("Пользователь отправил видео вместо фото")
        await update.message.reply_text(
            "⚠️ <b>Можно отправлять только фотографии!</b>\n\n"
            "Видео не поддерживаются.\n"
            "Пожалуйста, отправьте фото или:\n"
            "• Напишите /done_photos для завершения\n"
            "• Напишите: готово",
            parse_mode="HTML"
        )
        return REGISTER_MASTER_PHOTOS

    # КРИТИЧНО: Проверка на документы (файлы)
    if update.message.document:
        # Если это изображение-документ (файл), разрешаем
        if update.message.document.mime_type and update.message.document.mime_type.startswith('image/'):
            logger.info("Получено изображение как документ - обрабатываем как фото")
            # Обрабатываем как фото дальше по коду
        else:
            logger.warning(f"Пользователь отправил документ (не изображение): {update.message.document.mime_type}")
            await update.message.reply_text(
                "⚠️ <b>Можно отправлять только изображения!</b>\n\n"
                "Документы, видео и другие файлы не поддерживаются.\n"
                "Пожалуйста, отправьте фото или:\n"
                "• Напишите /done_photos для завершения\n"
                "• Напишите: готово",
                parse_mode="HTML"
            )
            return REGISTER_MASTER_PHOTOS

    # Проверяем текст сообщения
    if update.message.text:
        text = update.message.text.strip().lower()
        logger.info(f"Получен текст: '{text}'")

        # Проверяем различные варианты команды
        if text in ['/done_photos', 'done_photos', '/donephotos', 'donephotos', 'готово']:
            logger.info("Команда завершения фото распознана, вызываем finalize")
            return await finalize_master_registration(update, context)

    # Обработка фото
    if update.message.photo or (update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('image/')):
        logger.info("Получено фото")
        if "portfolio_photos" not in context.user_data:
            context.user_data["portfolio_photos"] = []

        # Получаем file_id (может быть photo или document)
        if update.message.photo:
            photo = update.message.photo[-1]  # Берём самое большое разрешение
            file_id = photo.file_id
        else:
            # Это document с image/ mime_type
            file_id = update.message.document.file_id

        # КРИТИЧНО: Валидация file_id
        if not validate_file_id(file_id):
            logger.error(f"❌ Невалидный file_id при загрузке фото портфолио: {file_id}")
            await update.message.reply_text(
                "❌ Ошибка при обработке фото.\n\n"
                "Попробуйте отправить фото еще раз или используйте другое изображение.\n\n"
                "Отправьте /done_photos для завершения регистрации без этого фото."
            )
            return REGISTER_MASTER_PHOTOS

        if len(context.user_data["portfolio_photos"]) < 4:
            context.user_data["portfolio_photos"].append(file_id)
            count = len(context.user_data["portfolio_photos"])
            logger.info(f"Фото добавлено. Всего: {count}")

            # Разные сообщения в зависимости от номера фото
            if count == 1:
                await update.message.reply_text(
                    "✅ <b>Фото #1 с вашим лицом добавлено!</b>\n\n"
                    "📸 <b>Теперь добавьте фото ваших работ</b> (до 3 штук):\n\n"
                    "Отправьте фотографии завершённых проектов, которыми вы гордитесь.\n\n"
                    "Когда загрузите все фото, напишите:\n"
                    "/done_photos или просто: готово",
                    parse_mode="HTML"
                )
            elif count < 4:
                await update.message.reply_text(
                    f"✅ Фото #{count} добавлено!\n\n"
                    f"📊 Загружено: {count}/4\n"
                    f"Можно ещё: {4 - count}\n\n"
                    f"Отправьте ещё фото или напишите:\n"
                    f"/done_photos (или: готово)",
                    parse_mode="HTML"
                )
            else:  # count == 4
                await update.message.reply_text(
                    "✅ Отлично! Все 4 фотографии загружены!\n\n"
                    "📝 Напишите /done_photos или просто: готово\n"
                    "чтобы завершить регистрацию."
                )
        else:
            await update.message.reply_text(
                "⚠️ Максимум 4 фотографии.\n\n"
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
    """
    Финальное создание профиля мастера.
    ИСПРАВЛЕНО: Валидация обязательных полей перед созданием.
    """
    telegram_id = update.effective_user.id if update.message else update.callback_query.from_user.id

    # КРИТИЧНО: Проверяем наличие всех обязательных полей
    required_fields = ["name", "phone", "city", "regions", "categories", "experience", "description"]
    ok, missing = validate_required_fields(context, required_fields)

    if not ok:
        logger.error(f"Missing required fields in master registration: {missing}")
        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")]]
        error_msg = (
            "❌ Ошибка: недостаточно данных для создания профиля.\n\n"
            "Пожалуйста, начните регистрацию заново: /start"
        )

        if update.message:
            await update.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))

        context.user_data.clear()
        return ConversationHandler.END

    # КРИТИЧНО: Обработка ошибок БД при создании пользователя и профиля
    user_created = False  # Флаг для отслеживания создания нового пользователя
    user_id = None

    try:
        # Проверяем существование пользователя перед созданием
        existing_user = db.get_user(telegram_id)
        if existing_user:
            user_id = existing_user['id']
            logger.info(f"Пользователь {telegram_id} уже существует, используем существующий ID: {user_id}")
        else:
            user_id = db.create_user(telegram_id, "worker")
            user_created = True  # КРИТИЧНО: Отмечаем что создали нового пользователя
            logger.info(f"Создан новый пользователь {telegram_id} с ID: {user_id}")

        # Сохраняем фото работ (если есть)
        portfolio_photos = context.user_data.get("portfolio_photos", [])

        # КРИТИЧНО: Дополнительная валидация всех file_id перед сохранением в БД
        valid_photos = [fid for fid in portfolio_photos if validate_file_id(fid)]
        if len(valid_photos) < len(portfolio_photos):
            removed_count = len(portfolio_photos) - len(valid_photos)
            logger.warning(f"⚠️ Удалено {removed_count} невалидных file_id перед сохранением профиля")

        photos_json = ",".join(valid_photos) if valid_photos else ""

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

    except ValueError as e:
        # Ошибки валидации (например, дубликат профиля из race condition protection)
        logger.error(f"❌ Ошибка валидации при создании профиля мастера: {e}")

        # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
        if user_created and user_id:
            try:
                db.delete_user_profile(telegram_id)
                logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")]]
        error_msg = (
            "❌ Не удалось создать профиль.\n\n"
            f"Причина: {str(e)}\n\n"
            "Попробуйте еще раз или обратитесь в поддержку."
        )
        if update.message:
            await update.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        # Любые другие ошибки БД (connection, SQL syntax, etc)
        logger.error(f"❌ Ошибка БД при создании профиля мастера: {e}", exc_info=True)

        # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
        if user_created and user_id:
            try:
                db.delete_user_profile(telegram_id)
                logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")]]
        error_msg = (
            "❌ Произошла ошибка при сохранении профиля в базу данных.\n\n"
            "Пожалуйста, попробуйте еще раз через минуту.\n\n"
            "Если проблема повторяется, обратитесь в поддержку."
        )
        if update.message:
            await update.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data.clear()
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("Моё меню мастера", callback_data="show_worker_menu")]]

    # Используем валидные фото для точной статистики
    photos_count = len(valid_photos)
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
        "Он необходим для регистрации и не будет виден всем подряд."
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

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"clientregion_{region_name}"
        )])

    await update.message.reply_text(
        "🏙 <b>Где вы находитесь?</b>\n\n"
        "Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REGISTER_CLIENT_REGION_SELECT


async def register_client_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора региона клиентом"""
    query = update.callback_query
    await query.answer()

    region = query.data.replace("clientregion_", "")
    region_data = BELARUS_REGIONS.get(region)

    if not region_data:
        await query.edit_message_text("❌ Ошибка выбора региона. Попробуйте снова.")
        return REGISTER_CLIENT_REGION_SELECT

    context.user_data["region"] = region

    # Если выбран Минск или "Вся Беларусь" - создаём профиль сразу
    if region_data["type"] in ["city", "country"]:
        context.user_data["city"] = region
        context.user_data["regions"] = region

        # Создаём профиль клиента
        telegram_id = query.from_user.id

        logger.info(f"=== Создание профиля клиента ===")
        logger.info(f"Telegram ID: {telegram_id}")
        logger.info(f"Имя: {context.user_data.get('name')}")
        logger.info(f"Телефон: {context.user_data.get('phone')}")
        logger.info(f"Регион: {region}")

        # КРИТИЧНО: Обработка ошибок БД при создании пользователя и профиля
        user_created = False  # Флаг для отслеживания создания нового пользователя
        user_id = None

        try:
            # Проверяем есть ли уже user (если добавляет вторую роль)
            existing_user = db.get_user(telegram_id)
            if existing_user:
                user_id = existing_user["id"]
                logger.info(f"Существующий user_id: {user_id}")
            else:
                user_id = db.create_user(telegram_id, "client")
                user_created = True  # КРИТИЧНО: Отмечаем что создали нового пользователя
                logger.info(f"Создан новый user_id: {user_id}")

            db.create_client_profile(
                user_id=user_id,
                name=context.user_data["name"],
                phone=context.user_data["phone"],
                city=context.user_data["city"],
                description="",
                regions=context.user_data["regions"],
            )
            logger.info("✅ Профиль клиента успешно создан в БД!")

        except ValueError as e:
            # Ошибки валидации (например, дубликат профиля)
            logger.error(f"❌ Ошибка валидации при создании профиля клиента: {e}")

            # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
            if user_created and user_id:
                try:
                    db.delete_user_profile(telegram_id)
                    logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
                except Exception as rollback_error:
                    logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

            await query.edit_message_text(
                f"❌ Не удалось создать профиль.\n\n"
                f"Причина: {str(e)}\n\n"
                f"Попробуйте еще раз или обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")
                ]])
            )
            context.user_data.clear()
            return ConversationHandler.END

        except Exception as e:
            # Любые другие ошибки БД
            logger.error(f"❌ Ошибка БД при создании профиля клиента: {e}", exc_info=True)

            # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
            if user_created and user_id:
                try:
                    db.delete_user_profile(telegram_id)
                    logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
                except Exception as rollback_error:
                    logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

            await query.edit_message_text(
                "❌ Произошла ошибка при сохранении профиля в базу данных.\n\n"
                "Пожалуйста, попробуйте еще раз через минуту.\n\n"
                "Если проблема повторяется, обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")
                ]])
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

    # Если выбрана область - показываем города
    else:
        cities = region_data.get("cities", [])
        keyboard = []
        row = []
        for city in cities:
            row.append(InlineKeyboardButton(city, callback_data=f"clientcity_{city}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:  # Добавляем оставшиеся города
            keyboard.append(row)

        # Добавляем кнопку "Другой город в области"
        keyboard.append([InlineKeyboardButton(
            f"📍 Другой город в области",
            callback_data="clientcity_other"
        )])

        await query.edit_message_text(
            f"🏙 Выберите город в регионе <b>{region}</b>:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REGISTER_CLIENT_CITY_SELECT


async def register_client_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города клиентом после выбора региона"""
    query = update.callback_query
    await query.answer()

    city = query.data.replace("clientcity_", "")

    if city == "other":
        region = context.user_data.get("region", "")
        await query.edit_message_text(
            f"🏙 Напишите название города в регионе <b>{region}</b>:",
            parse_mode="HTML"
        )
        return REGISTER_CLIENT_CITY_OTHER
    else:
        context.user_data["city"] = city
        region = context.user_data.get("region", city)
        context.user_data["regions"] = region

        # Создаём профиль
        telegram_id = query.from_user.id

        logger.info(f"=== Создание профиля клиента ===")
        logger.info(f"Telegram ID: {telegram_id}")
        logger.info(f"Имя: {context.user_data.get('name')}")
        logger.info(f"Телефон: {context.user_data.get('phone')}")
        logger.info(f"Город: {city}")
        logger.info(f"Регион: {region}")

        # КРИТИЧНО: Обработка ошибок БД при создании пользователя и профиля
        user_created = False  # Флаг для отслеживания создания нового пользователя
        user_id = None

        try:
            # Проверяем есть ли уже user (если добавляет вторую роль)
            existing_user = db.get_user(telegram_id)
            if existing_user:
                user_id = existing_user["id"]
                logger.info(f"Существующий user_id: {user_id}")
            else:
                user_id = db.create_user(telegram_id, "client")
                user_created = True  # КРИТИЧНО: Отмечаем что создали нового пользователя
                logger.info(f"Создан новый user_id: {user_id}")

            db.create_client_profile(
                user_id=user_id,
                name=context.user_data["name"],
                phone=context.user_data["phone"],
                city=context.user_data["city"],
                description="",
                regions=context.user_data["regions"],
            )
            logger.info("✅ Профиль клиента успешно создан в БД!")

        except ValueError as e:
            # Ошибки валидации (например, дубликат профиля)
            logger.error(f"❌ Ошибка валидации при создании профиля клиента: {e}")

            # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
            if user_created and user_id:
                try:
                    db.delete_user_profile(telegram_id)
                    logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
                except Exception as rollback_error:
                    logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

            await query.edit_message_text(
                f"❌ Не удалось создать профиль.\n\n"
                f"Причина: {str(e)}\n\n"
                f"Попробуйте еще раз или обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")
                ]])
            )
            context.user_data.clear()
            return ConversationHandler.END

        except Exception as e:
            # Любые другие ошибки БД
            logger.error(f"❌ Ошибка БД при создании профиля клиента: {e}", exc_info=True)

            # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
            if user_created and user_id:
                try:
                    db.delete_user_profile(telegram_id)
                    logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
                except Exception as rollback_error:
                    logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

            await query.edit_message_text(
                "❌ Произошла ошибка при сохранении профиля в базу данных.\n\n"
                "Пожалуйста, попробуйте еще раз через минуту.\n\n"
                "Если проблема повторяется, обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")
                ]])
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
    """Ввод другого города клиентом вручную"""
    city = update.message.text.strip()
    context.user_data["city"] = city
    region = context.user_data.get("region", city)
    context.user_data["regions"] = region

    # Создаём профиль
    telegram_id = update.effective_user.id

    # КРИТИЧНО: Обработка ошибок БД при создании пользователя и профиля
    user_created = False  # Флаг для отслеживания создания нового пользователя
    user_id = None

    try:
        # Проверяем есть ли уже user (если добавляет вторую роль)
        existing_user = db.get_user(telegram_id)
        if existing_user:
            user_id = existing_user["id"]
        else:
            user_id = db.create_user(telegram_id, "client")
            user_created = True  # КРИТИЧНО: Отмечаем что создали нового пользователя

        db.create_client_profile(
            user_id=user_id,
            name=context.user_data["name"],
            phone=context.user_data["phone"],
            city=context.user_data["city"],
            description="",
            regions=context.user_data["regions"],
        )

    except ValueError as e:
        # Ошибки валидации (например, дубликат профиля)
        logger.error(f"❌ Ошибка валидации при создании профиля клиента: {e}")

        # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
        if user_created and user_id:
            try:
                db.delete_user_profile(telegram_id)
                logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")]]
        await update.message.reply_text(
            f"❌ Не удалось создать профиль.\n\n"
            f"Причина: {str(e)}\n\n"
            f"Попробуйте еще раз или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        # Любые другие ошибки БД
        logger.error(f"❌ Ошибка БД при создании профиля клиента: {e}", exc_info=True)

        # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
        if user_created and user_id:
            try:
                db.delete_user_profile(telegram_id)
                logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")]]
        await update.message.reply_text(
            "❌ Произошла ошибка при сохранении профиля в базу данных.\n\n"
            "Пожалуйста, попробуйте еще раз через минуту.\n\n"
            "Если проблема повторяется, обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data.clear()
        return ConversationHandler.END

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
        [InlineKeyboardButton("💼 Мои отклики", callback_data="worker_my_bids")],
        [InlineKeyboardButton("📦 Мои заказы", callback_data="worker_my_orders")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="worker_profile")],
        [InlineKeyboardButton(f"{notification_status} Уведомления", callback_data="toggle_notifications")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")],
    ]

    # Удаляем старое сообщение и отправляем новое
    # (работает с любым типом сообщения: текст, фото, медиа)
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="🧰 <b>Меню мастера</b>\n\n"
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

    # ИСПРАВЛЕНО: Вынесли текст в переменные (нельзя использовать \n внутри f-string expression)
    notification_on_text = 'Вы будете получать уведомления о новых заказах в вашем городе и категориях.'
    notification_off_text = 'Вы НЕ будете получать уведомления о новых заказах. Вы можете просматривать заказы вручную в разделе "Доступные заказы".'

    await query.edit_message_text(
        f"🔔 <b>Уведомления {status_text}</b>\n\n"
        f"{notification_on_text if new_status else notification_off_text}\n\n"
        "Возвращаемся в меню...",
        parse_mode="HTML"
    )

    # Возвращаемся в меню мастера через 2 секунды
    await asyncio.sleep(2)
    await show_worker_menu(update, context)


async def worker_my_bids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все отклики мастера с их статусами"""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    # Получаем профиль мастера
    worker = db.get_worker_by_user_id(user['id'])
    if not worker:
        await query.edit_message_text(
            "❌ Профиль мастера не найден.\n\n"
            "Возможно, вы зарегистрированы как заказчик."
        )
        return

    worker_dict = dict(worker)

    # Получаем все отклики мастера
    bids = db.get_bids_for_worker(worker_dict['id'])

    if not bids:
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")]]
        await query.edit_message_text(
            "💼 <b>Мои отклики</b>\n\n"
            "У вас пока нет откликов на заказы.\n\n"
            "Перейдите в раздел \"Доступные заказы\" и откликнитесь на интересные вам заказы!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Группируем отклики по статусам
    pending_bids = []
    selected_bids = []
    rejected_bids = []

    for bid in bids:
        bid_dict = dict(bid)
        if bid_dict['status'] == 'pending':
            pending_bids.append(bid_dict)
        elif bid_dict['status'] == 'selected':
            selected_bids.append(bid_dict)
        elif bid_dict['status'] == 'rejected':
            rejected_bids.append(bid_dict)

    # Формируем текст с откликами
    text = "💼 <b>Мои отклики</b>\n\n"

    if selected_bids:
        text += "✅ <b>Выбраны клиентом:</b>\n"
        for bid in selected_bids[:5]:  # Показываем до 5 выбранных
            order_title = bid.get('order_title') or 'Без названия'
            order_title_short = order_title[:30] + '...' if len(order_title) > 30 else order_title
            text += f"  • {order_title_short} - {bid['proposed_price']} {bid['currency']}\n"
            text += f"    Статус заказа: {_get_order_status_text(bid['order_status'])}\n"
        text += "\n"

    if pending_bids:
        text += "⏳ <b>Ожидают ответа клиента:</b>\n"
        for bid in pending_bids[:5]:  # Показываем до 5 ожидающих
            order_title = bid.get('order_title') or 'Без названия'
            order_title_short = order_title[:30] + '...' if len(order_title) > 30 else order_title
            text += f"  • {order_title_short} - {bid['proposed_price']} {bid['currency']}\n"
        if len(pending_bids) > 5:
            text += f"  ... и ещё {len(pending_bids) - 5}\n"
        text += "\n"

    if rejected_bids:
        text += f"❌ <b>Отклонены:</b> {len(rejected_bids)}\n"

    text += f"\n📊 <b>Всего откликов:</b> {len(bids)}"

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")]]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def worker_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Показывает мастеру его заказы в работе (подтвержденные заказы).
    """
    query = update.callback_query
    await query.answer()

    try:
        # Получаем пользователя и профиль мастера
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict["id"])
        if not worker_profile:
            await safe_edit_message(
                query,
                "❌ Профиль мастера не найден.\n\n"
                "Возможно произошла ошибка при регистрации.\n"
                "Нажмите /start и зарегистрируйтесь заново.",
                parse_mode="HTML"
            )
            return

        worker_dict = dict(worker_profile)

        # Получаем все отклики мастера
        bids = db.get_bids_for_worker(worker_dict['id'])

        # Фильтруем только выбранные отклики (заказы в работе)
        active_orders = []
        for bid in bids:
            bid_dict = dict(bid)
            if bid_dict['status'] == 'selected':
                # Получаем актуальный статус заказа
                order = db.get_order_by_id(bid_dict['order_id'])
                if order:
                    order_dict = dict(order)
                    # Показываем только заказы в работе (не завершенные)
                    if order_dict['status'] in ('master_selected', 'contact_shared', 'master_confirmed'):
                        bid_dict['order_status'] = order_dict['status']
                        bid_dict['order_city'] = order_dict.get('city', 'Не указан')
                        bid_dict['order_description'] = order_dict.get('description', '')
                        active_orders.append(bid_dict)

        # Формируем текст и кнопки
        text = "📦 <b>Мои заказы в работе</b>\n\n"
        keyboard = []

        if active_orders:
            for i, order in enumerate(active_orders[:10], 1):  # Показываем до 10
                order_title = order.get('order_title') or 'Без названия'
                order_title_short = order_title[:40] + '...' if len(order_title) > 40 else order_title

                text += f"{i}. <b>{order_title_short}</b>\n"
                text += f"   📍 {order.get('order_city', 'Не указан')}\n"
                text += f"   💰 {order['proposed_price']} {order['currency']}\n"
                text += f"   📊 Статус: {_get_order_status_text(order.get('order_status', 'unknown'))}\n"
                text += "\n"

                # Добавляем кнопку для открытия чата с клиентом
                chat = db.get_chat_by_order(order['order_id'])
                if chat:
                    chat_dict = dict(chat)
                    keyboard.append([InlineKeyboardButton(
                        f"💬 Чат по заказу #{order['order_id']}",
                        callback_data=f"open_chat_{chat_dict['id']}"
                    )])

                # КРИТИЧНО: Мастер тоже может завершить заказ независимо!
                # Защита от недобросовестных клиентов, которые не завершают заказ
                keyboard.append([InlineKeyboardButton(
                    f"✅ Завершить заказ #{order['order_id']}",
                    callback_data=f"complete_order_{order['order_id']}"
                )])

            if len(active_orders) > 10:
                text += f"... и ещё {len(active_orders) - 10} заказов\n\n"

            text += f"<b>Всего активных заказов:</b> {len(active_orders)}"
        else:
            text += "У вас пока нет заказов в работе.\n\n"
            text += "Когда клиент выберет ваш отклик, заказ появится здесь."

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")])

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в worker_my_orders: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка при загрузке заказов:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")
            ]])
        )


def _get_order_status_text(status):
    """Возвращает читаемый текст статуса заказа"""
    status_map = {
        'open': '🟢 Открыт',
        'waiting_master_confirmation': '⏳ Ожидает подтверждения',
        'master_confirmed': '✅ Мастер подтвердил',
        'master_selected': '👤 Мастер выбран',
        'completed': '✅ Завершен',
        'cancelled': '❌ Отменён'
    }
    return status_map.get(status, status)


async def show_client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📝 Создать заказ", callback_data="client_create_order")],
        [InlineKeyboardButton("📂 Мои заказы", callback_data="client_my_orders")],
        [InlineKeyboardButton("💳 Мои платежи", callback_data="client_my_payments")],
        [InlineKeyboardButton("🔍 Найти мастера", callback_data="client_browse_workers")],
        [InlineKeyboardButton("🧰 Главное меню", callback_data="go_main_menu")],
    ]

    # Удаляем старое сообщение и отправляем новое
    # (работает с любым типом сообщения: текст, фото, медиа)
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="🏠 <b>Меню заказчика</b>\n\n"
             "Создайте заказ - мастера увидят его и откликнутся!\n"
             "Или найдите мастера самостоятельно.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def client_my_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю платежей клиента"""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    # Получаем историю транзакций
    transactions = db.get_user_transactions(user['id'])

    if not transactions:
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_client_menu")]]
        await query.edit_message_text(
            "💳 <b>Мои платежи</b>\n\n"
            "У вас пока нет платежей.\n\n"
            "Когда вы выберете мастера для заказа и оплатите доступ к его контактам, "
            "платежи будут отображаться здесь.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Формируем текст с платежами
    text = "💳 <b>Мои платежи</b>\n\n"

    total_spent = 0.0

    for transaction in transactions[:10]:  # Показываем последние 10 платежей
        trans_dict = dict(transaction)
        amount = float(trans_dict['amount'])
        currency = trans_dict['currency']
        total_spent += amount

        # Форматируем дату
        from datetime import datetime
        created_at = datetime.fromisoformat(trans_dict['created_at'])
        date_str = created_at.strftime("%d.%m.%Y %H:%M")

        # Получаем описание или тип транзакции
        description = trans_dict.get('description', '')
        if not description:
            trans_type = trans_dict.get('transaction_type', 'payment')
            description = f"Платёж ({trans_type})"

        # Статус транзакции
        status = trans_dict.get('status', 'unknown')
        status_emoji = "✅" if status == 'completed' else "⏳" if status == 'pending' else "❌"

        text += f"{status_emoji} <b>{amount:.2f} {currency}</b>\n"
        text += f"  {description[:50]}{'...' if len(description) > 50 else ''}\n"
        text += f"  📅 {date_str}\n\n"

    if len(transactions) > 10:
        text += f"... и ещё {len(transactions) - 10} платежей\n\n"

    text += f"💰 <b>Всего потрачено:</b> {total_spent:.2f} BYN\n"
    text += f"📊 <b>Количество платежей:</b> {len(transactions)}"

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_client_menu")]]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
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
            "⚠️ <b>Напоминание:</b> Первое фото должно быть с вашим лицом!\n\n"
            "Чтобы изменить фото, удалите старые через меню редактирования.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
            ])
        )
        context.user_data.clear()
        return

    # Если это первое фото
    if current_count == 0:
        hint_text = "🤵 <b>Первое фото должно быть с вашим лицом!</b>\n" \
                   "Это повышает доверие клиентов.\n\n" \
                   "После можете добавить до 9 фотографий ваших работ и 1 видео."
    else:
        hint_text = f"📊 Загружено: {current_count}/10\n" \
                   f"Можно добавить ещё: {available_slots} фото/видео работ"

    await query.edit_message_text(
        f"📸 <b>Добавление фото в портфолио</b>\n\n"
        f"{hint_text}\n\n"
        f"Отправьте фотографии (можно по одной или группой).\n\n"
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
    is_video = False

    # Обработка фото (сжатое изображение)
    if update.message and update.message.photo:
        logger.info("Получено фото (photo) для добавления в портфолио")
        photo = update.message.photo[-1]  # Берём самое большое разрешение
        file_id = photo.file_id

    # Обработка видео
    elif update.message and update.message.video:
        # Проверяем, не загружено ли уже видео
        existing_videos = [p for p in context.user_data.get("existing_photos", []) if p.startswith("VIDEO:")]
        new_videos = [p for p in context.user_data.get("new_photos", []) if p.startswith("VIDEO:")]
        if len(existing_videos) + len(new_videos) >= 1:
            keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
            await update.message.reply_text(
                "⚠️ Можно загрузить максимум 1 видео.\n\n"
                "У вас уже есть видео в портфолио.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        logger.info("Получено видео для добавления в портфолио")
        video = update.message.video
        file_id = "VIDEO:" + video.file_id
        is_video = True

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
                "❌ Можно отправлять только изображения (JPG, PNG и т.д.) или видео.\n\n"
                "Попробуйте отправить фото/видео еще раз.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    if not file_id:
        logger.warning("Не удалось получить file_id из сообщения")
        return

    # КРИТИЧНО: Валидация file_id
    if not validate_file_id(file_id):
        logger.error(f"❌ Невалидный file_id при добавлении фото в портфолио: {file_id}")
        keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
        await update.message.reply_text(
            "❌ Ошибка при обработке фото.\n\n"
            "Попробуйте отправить фото еще раз или используйте другое изображение.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
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

    media_type = "Видео" if is_video else "Фото"
    logger.info(f"{media_type} добавлено. Новых: {new_count}, Всего: {total_count}")

    # ДОБАВЛЯЕМ КНОПКУ для завершения
    keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]

    await update.message.reply_text(
        f"✅ {media_type} #{total_count} добавлено!\n\n"
        f"📊 Статус:\n"
        f"• Было: {existing_count}\n"
        f"• Добавлено новых: {new_count}\n"
        f"• Всего будет: {total_count}/{max_photos}\n"
        f"• Можно ещё: {remaining}\n\n"
        f"Отправьте ещё фото/видео или нажмите кнопку:",
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

        # КРИТИЧНО: Валидация всех file_id перед сохранением в БД
        valid_photos = [fid for fid in all_photos if validate_file_id(fid)]
        if len(valid_photos) < len(all_photos):
            removed_count = len(all_photos) - len(valid_photos)
            logger.warning(f"⚠️ Удалено {removed_count} невалидных file_id перед обновлением портфолио")

        photos_string = ",".join(valid_photos)

        logger.info(f"Объединённые фото (всего {len(valid_photos)} валидных из {len(all_photos)})")
        
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

        # Подсчитываем валидные фото (для точной статистики)
        valid_new_photos = [fid for fid in new_photos if validate_file_id(fid)]
        added_count = len(valid_new_photos)
        total_count = len(valid_photos)
        
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

    # КРИТИЧНО: Валидация file_id
    if not validate_file_id(file_id):
        logger.error(f"❌ Невалидный file_id при загрузке фото профиля: {file_id}")
        await update.message.reply_text(
            "❌ Ошибка при обработке фото.\n\n"
            "Попробуйте отправить фото еще раз или используйте другое изображение.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_profile_photo")
            ]])
        )
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

    # Удаляем старое сообщение и отправляем новое
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="✏️ <b>Редактирование профиля</b>\n\n"
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
    """Начало редактирования города - выбор региона"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_city = profile_dict.get("city") or "—"

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"editregion_{region_name}"
        )])

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

    await query.edit_message_text(
        f"🏙 <b>Изменение города</b>\n\n"
        f"Текущий город: <b>{current_city}</b>\n\n"
        f"Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EDIT_REGION_SELECT




async def edit_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора региона при редактировании города"""
    query = update.callback_query
    await query.answer()

    region = query.data.replace("editregion_", "")
    region_data = BELARUS_REGIONS.get(region)

    if not region_data:
        await query.edit_message_text("❌ Ошибка выбора региона. Попробуйте снова.")
        return EDIT_REGION_SELECT

    context.user_data["edit_region"] = region

    # Если выбран Минск или "Вся Беларусь" - сразу сохраняем
    if region_data["type"] in ["city", "country"]:
        telegram_id = query.from_user.id
        user = db.get_user(telegram_id)
        user_dict = dict(user)
        user_id = user_dict.get("id")

        db.update_worker_field(user_id, "city", region)
        db.update_worker_field(user_id, "regions", region)

        keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]

        await query.edit_message_text(
            f"✅ Город успешно изменён на: <b>{region_data['display']}</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # Если выбрана область - показываем города
    else:
        cities = region_data.get("cities", [])
        keyboard = []
        row = []
        for city in cities:
            row.append(InlineKeyboardButton(city, callback_data=f"editcity_{city}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Добавляем кнопку "Другой город в области"
        keyboard.append([InlineKeyboardButton(
            f"📍 Другой город в области",
            callback_data="editcity_other"
        )])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

        await query.edit_message_text(
            f"📍 Область: {region_data['display']}\n\n"
            "🏙 Выберите город:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return EDIT_CITY


async def edit_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города из списка при редактировании"""
    query = update.callback_query
    await query.answer()

    city = query.data.replace("editcity_", "")

    if city == "other":
        await query.edit_message_text(
            "🏙 Напишите название города:"
        )
        return EDIT_CITY
    else:
        # Сохраняем город
        telegram_id = query.from_user.id
        user = db.get_user(telegram_id)
        user_dict = dict(user)
        user_id = user_dict.get("id")

        region = context.user_data.get("edit_region", city)
        db.update_worker_field(user_id, "city", city)
        db.update_worker_field(user_id, "regions", region)

        keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]

        await query.edit_message_text(
            f"✅ Город успешно изменён на: <b>{city}</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return ConversationHandler.END



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

    # Показываем 7 основных категорий
    keyboard = []
    for cat_id, category_data in WORK_CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(
                category_data["name"],
                callback_data=f"editmaincat_{cat_id}"
            )])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

    await query.edit_message_text(
        f"🔧 <b>Изменение видов работ</b>\n\n"
        f"Текущие категории:\n<b>{current_categories}</b>\n\n"
        f"Выберите основную категорию работ:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return EDIT_MAIN_CATEGORY


async def edit_main_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора основной категории при редактировании"""
    query = update.callback_query
    await query.answer()

    cat_id = query.data.replace("editmaincat_", "")
    category_name = WORK_CATEGORIES[cat_id]["name"]
    context.user_data["edit_current_main_category"] = cat_id

    # Получаем подкатегории для выбранной категории
    subcategories = WORK_CATEGORIES[cat_id]["subcategories"]

    # Создаем кнопки подкатегорий (2 в ряд) с галочками
    keyboard = []
    row = []
    for idx, subcat in enumerate(subcategories):
        # Проверяем выбрана ли уже эта подкатегория
        is_selected = subcat in context.user_data.get("edit_categories", [])
        button_text = f"✅ {subcat}" if is_selected else subcat

        row.append(InlineKeyboardButton(button_text, callback_data=f"editsubcat_{cat_id}:{idx}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Добавляем кнопку завершения
    keyboard.append([InlineKeyboardButton("✅ Завершить выбор категорий", callback_data="editsubcat_done")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

    emoji = WORK_CATEGORIES[cat_id]["emoji"]

    await query.edit_message_text(
        f"{emoji} <b>Категория:</b> {category_name}\n\n"
        "🔧 <b>Выберите подкатегории:</b>\n\n"
        "Нажимайте подходящие кнопки (можно несколько).\n"
        "Когда закончите — нажмите «✅ Завершить выбор категорий».",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EDIT_SUBCATEGORY_SELECT


async def edit_subcategory_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора подкатегорий при редактировании"""
    query = update.callback_query
    await query.answer()
    data = query.data
    selected = data.replace("editsubcat_", "")

    if selected == "done":
        # Проверяем что выбрана хотя бы одна подкатегория
        if not context.user_data.get("edit_categories"):
            await query.answer("Выберите хотя бы одну подкатегорию!", show_alert=True)
            return EDIT_SUBCATEGORY_SELECT

        # Спрашиваем хочет ли добавить еще категории
        keyboard = [
            [InlineKeyboardButton("✅ Да, добавить еще", callback_data="editmore_yes")],
            [InlineKeyboardButton("💾 Нет, сохранить изменения", callback_data="editmore_no")],
        ]

        categories_text = ", ".join(context.user_data["edit_categories"])

        await query.edit_message_text(
            f"✅ <b>Выбранные категории:</b>\n{categories_text}\n\n"
            "Хотите добавить еще категории из других разделов?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return EDIT_ASK_MORE_CATEGORIES

    else:
        # Парсим cat_id:index из callback_data
        cat_id, idx_str = selected.split(":")
        idx = int(idx_str)
        subcat_name = WORK_CATEGORIES[cat_id]["subcategories"][idx]

        # Переключаем выбор подкатегории
        if "edit_categories" not in context.user_data:
            context.user_data["edit_categories"] = []

        if subcat_name not in context.user_data["edit_categories"]:
            context.user_data["edit_categories"].append(subcat_name)
            await query.answer(f"✅ Добавлено: {subcat_name}")
        else:
            context.user_data["edit_categories"].remove(subcat_name)
            await query.answer(f"❌ Убрано: {subcat_name}")

        # Обновляем кнопки с галочками
        main_category = context.user_data["edit_current_main_category"]
        subcategories = WORK_CATEGORIES[cat_id]["subcategories"]
        category_name = WORK_CATEGORIES[cat_id]["name"]

        keyboard = []
        row = []
        for idx2, subcat in enumerate(subcategories):
            is_selected = subcat in context.user_data["edit_categories"]
            button_text = f"✅ {subcat}" if is_selected else subcat

            row.append(InlineKeyboardButton(button_text, callback_data=f"editsubcat_{cat_id}:{idx2}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("✅ Завершить выбор категорий", callback_data="editsubcat_done")])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

        emoji = WORK_CATEGORIES[cat_id]["emoji"]

        await query.edit_message_text(
            f"{emoji} <b>Категория:</b> {category_name}\n\n"
            "🔧 <b>Выберите подкатегории:</b>\n\n"
            "Нажимайте подходящие кнопки (можно несколько).\n"
            "Когда закончите — нажмите «✅ Завершить выбор категорий».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return EDIT_SUBCATEGORY_SELECT


async def edit_ask_more_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Спрашиваем хочет ли добавить еще категории при редактировании"""
    query = update.callback_query
    await query.answer()

    choice = query.data.replace("editmore_", "")

    if choice == "yes":
        # Возвращаемся к выбору основной категории
        keyboard = []
        for cat_id, category_data in WORK_CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(
                category_data["name"],
                callback_data=f"editmaincat_{cat_id}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

        categories_text = ", ".join(context.user_data["edit_categories"])

        await query.edit_message_text(
            f"✅ <b>Уже выбрано:</b> {categories_text}\n\n"
            "🔧 <b>Выберите основную категорию для добавления:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return EDIT_MAIN_CATEGORY

    else:
        # Сохраняем изменения
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
        [InlineKeyboardButton("🌱 Начинающий мастер", callback_data="editexp_Начинающий мастер")],
        [InlineKeyboardButton("⚡ Опытный мастер", callback_data="editexp_Опытный мастер")],
        [InlineKeyboardButton("⭐ Профессионал", callback_data="editexp_Профессионал")],
        [InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")],
    ]

    await query.edit_message_text(
        f"📊 <b>Изменение уровня мастерства</b>\n\n"
        f"Текущий уровень: <b>{current_exp}</b>\n\n"
        f"Выберите новый уровень:\n\n"
        "🌱 <b>Начинающий мастер</b> — осваиваете профессию\n"
        "⚡ <b>Опытный мастер</b> — есть портфолио проектов\n"
        "⭐ <b>Профессионал</b> — высокий уровень, сложные проекты",
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

            # НОВОЕ: Кнопка отмены для открытых заказов
            order_status = order_dict.get('status', '')
            if order_status in ('open', 'waiting_master_confirmation'):
                keyboard.append([InlineKeyboardButton(
                    f"❌ Отменить заказ #{order_id}",
                    callback_data=f"cancel_order_{order_id}"
                )])

            # НОВОЕ: Если мастер выбран, показываем кнопки чата и завершения
            selected_worker_id = order_dict.get('selected_worker_id')
            if selected_worker_id:
                # Проверяем существует ли чат
                chat = db.get_chat_by_order(order_id)
                if chat:
                    chat_dict = dict(chat)
                    keyboard.append([InlineKeyboardButton(
                        f"💬 Чат с мастером",
                        callback_data=f"open_chat_{chat_dict['id']}"
                    )])

                # КРИТИЧНО: Кнопка завершения доступна СРАЗУ после выбора мастера
                # Клиент НЕ зависит от подтверждения мастера!
                if order_status not in ('done', 'completed', 'cancelled'):
                    keyboard.append([InlineKeyboardButton(
                        f"✅ Завершить заказ #{order_id}",
                        callback_data=f"complete_order_{order_id}"
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


async def cancel_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Обработчик отмены заказа клиентом.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем order_id из callback_data
        order_id = int(query.data.replace("cancel_order_", ""))

        # Получаем пользователя
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Пользователь не найден.")
            return

        # Отменяем заказ
        result = db.cancel_order(order_id, user['id'], reason="Отменен клиентом через бот")

        if not result['success']:
            await query.edit_message_text(
                f"❌ <b>Ошибка отмены заказа</b>\n\n{result['message']}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад к заказам", callback_data="client_my_orders")
                ]])
            )
            return

        # Успешная отмена - уведомляем мастеров
        notified_count = 0
        for worker_user_id in result['notified_workers']:
            try:
                worker_user = db.get_user_by_id(worker_user_id)
                if worker_user:
                    await context.bot.send_message(
                        chat_id=worker_user['telegram_id'],
                        text=(
                            f"❌ <b>Заказ #{order_id} отменен</b>\n\n"
                            f"Клиент отменил заказ на который вы откликались.\n"
                            f"Ваш отклик больше не актуален."
                        ),
                        parse_mode="HTML"
                    )
                    notified_count += 1
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление мастеру {worker_user_id}: {e}")

        # Сообщаем клиенту об успехе
        await query.edit_message_text(
            f"✅ <b>Заказ #{order_id} успешно отменен</b>\n\n"
            f"📨 Уведомлено мастеров: {notified_count}\n\n"
            f"Заказ больше не будет показываться в поиске.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📂 Мои заказы", callback_data="client_my_orders"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="show_client_menu")
            ]])
        )

        logger.info(f"Заказ {order_id} отменен пользователем {user['id']}. Уведомлено мастеров: {notified_count}")

    except Exception as e:
        logger.error(f"Ошибка при отмене заказа: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка при отмене заказа:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="client_my_orders")
            ]])
        )


async def complete_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ОБНОВЛЕНО: Обработчик завершения заказа с оценкой - работает для ОБЕИХ сторон.
    Клиент оценивает мастера, мастер оценивает клиента.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем order_id из callback_data
        order_id = int(query.data.replace("complete_order_", ""))

        # Получаем пользователя
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Пользователь не найден.")
            return

        user_dict = dict(user)

        # Получаем заказ
        order = db.get_order_by_id(order_id)
        if not order:
            await query.edit_message_text("❌ Заказ не найден.")
            return

        order_dict = dict(order)

        # Проверяем статус заказа - нельзя завершить уже завершённый или отменённый
        if order_dict['status'] in ('done', 'completed', 'cancelled'):
            await safe_edit_message(
                query,
                f"❌ Этот заказ уже завершён или отменён.\n\n"
                f"Статус: {order_dict['status']}",
                parse_mode="HTML"
            )
            return

        # Получаем выбранного мастера
        selected_worker_id = order_dict.get('selected_worker_id')
        if not selected_worker_id:
            await safe_edit_message(
                query,
                "❌ Для завершения заказа необходимо сначала выбрать мастера.",
                parse_mode="HTML"
            )
            return

        # КРИТИЧНО: Определяем, кто вызывает - клиент или мастер
        client_profile = db.get_client_profile(user_dict["id"])
        worker_profile_caller = db.get_worker_profile(user_dict["id"])

        is_client = client_profile and order_dict['client_id'] == dict(client_profile)['id']
        is_worker = worker_profile_caller and dict(worker_profile_caller)['id'] == selected_worker_id

        if not is_client and not is_worker:
            await safe_edit_message(query, "❌ Вы не являетесь участником этого заказа.")
            return

        # Проверяем, не оставлен ли уже отзыв этим пользователем
        existing_review = db.check_review_exists(order_id, user_dict['id'])
        if existing_review:
            await safe_edit_message(
                query,
                "✅ Вы уже завершили этот заказ и оставили отзыв.",
                parse_mode="HTML"
            )
            return

        # Получаем информацию о противоположной стороне
        if is_client:
            # Клиент оценивает мастера
            target_profile = db.get_worker_by_id(selected_worker_id)
            if not target_profile:
                await safe_edit_message(query, "❌ Информация о мастере не найдена.")
                return
            target_dict = dict(target_profile)
            target_name = target_dict.get('name', 'Без имени')
            target_role = "Мастер"
            cancel_callback = "client_my_orders"
        else:
            # Мастер оценивает клиента
            client_data = db.get_client_by_id(order_dict['client_id'])
            if not client_data:
                await safe_edit_message(query, "❌ Информация о клиенте не найдена.")
                return
            client_dict = dict(client_data)
            client_user = db.get_user_by_id(client_dict['user_id'])
            if not client_user:
                await safe_edit_message(query, "❌ Информация о клиенте не найдена.")
                return
            client_user_dict = dict(client_user)
            target_name = client_user_dict.get('first_name', 'Клиент')
            target_role = "Клиент"
            cancel_callback = "worker_my_orders"

        # Показываем форму оценки
        text = (
            f"✅ <b>Завершение заказа #{order_id}</b>\n\n"
            f"👤 <b>{target_role}:</b> {target_name}\n\n"
            f"📊 <b>Оцените {'работу мастера' if is_client else 'клиента'}:</b>\n"
            f"Ваша оценка поможет {'другим клиентам' if is_client else 'другим мастерам'} сделать правильный выбор."
        )

        # Кнопки с оценками от 1 до 5 звезд
        # Формат callback: rate_order_{order_id}_{rating}_{role}
        # role: 'client' если оценивает клиент, 'worker' если оценивает мастер
        role_suffix = 'client' if is_client else 'worker'
        keyboard = [
            [
                InlineKeyboardButton("⭐", callback_data=f"rate_order_{order_id}_1_{role_suffix}"),
                InlineKeyboardButton("⭐⭐", callback_data=f"rate_order_{order_id}_2_{role_suffix}"),
                InlineKeyboardButton("⭐⭐⭐", callback_data=f"rate_order_{order_id}_3_{role_suffix}"),
            ],
            [
                InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rate_order_{order_id}_4_{role_suffix}"),
                InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_order_{order_id}_5_{role_suffix}"),
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data=cancel_callback)]
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        logger.info(f"{'Клиент' if is_client else 'Мастер'} {user_dict['id']} открыл форму завершения заказа {order_id}")

    except Exception as e:
        logger.error(f"Ошибка при открытии формы завершения заказа: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def submit_order_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ОБНОВЛЕНО: Обработчик сохранения оценки заказа - работает для ОБЕИХ сторон.
    Callback data format: rate_order_{order_id}_{rating}_{role}
    role: 'client' (клиент оценивает мастера) или 'worker' (мастер оценивает клиента)
    """
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем order_id, rating и role из callback_data
        # Формат: rate_order_{order_id}_{rating}_{role}
        data_parts = query.data.replace("rate_order_", "").split("_")
        order_id = int(data_parts[0])
        rating = int(data_parts[1])
        role = data_parts[2] if len(data_parts) > 2 else 'client'  # По умолчанию клиент (обратная совместимость)

        is_client = (role == 'client')

        # Получаем пользователя
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)

        # Получаем заказ
        order = db.get_order_by_id(order_id)
        if not order:
            await safe_edit_message(query, "❌ Заказ не найден.")
            return

        order_dict = dict(order)

        # Получаем выбранного мастера
        selected_worker_id = order_dict.get('selected_worker_id')
        if not selected_worker_id:
            await safe_edit_message(query, "❌ Мастер не выбран.")
            return

        # Получаем информацию о мастере
        worker_profile = db.get_worker_by_id(selected_worker_id)
        if not worker_profile:
            await safe_edit_message(query, "❌ Информация о мастере не найдена.")
            return

        worker_dict = dict(worker_profile)
        worker_user_id = worker_dict['user_id']

        # Получаем информацию о клиенте
        client_data = db.get_client_by_id(order_dict['client_id'])
        if not client_data:
            await safe_edit_message(query, "❌ Информация о клиенте не найдена.")
            return
        client_dict = dict(client_data)
        client_user_id = client_dict['user_id']

        # Сохраняем отзыв в зависимости от того, кто оценивает
        if is_client:
            # Клиент оценивает мастера
            review_saved = db.add_review(
                from_user_id=user_dict['id'],
                to_user_id=worker_user_id,
                order_id=order_id,
                role_from='client',
                role_to='worker',
                rating=rating,
                comment=None
            )
            target_name = worker_dict.get('name', 'Без имени')
            target_role = "мастера"
            return_callback = "client_my_orders"
            return_menu_callback = "show_client_menu"
            notify_user_id = worker_user_id
            notify_text_prefix = "Клиент завершил заказ и оставил вам оценку"
        else:
            # Мастер оценивает клиента
            review_saved = db.add_review(
                from_user_id=user_dict['id'],
                to_user_id=client_user_id,
                order_id=order_id,
                role_from='worker',
                role_to='client',
                rating=rating,
                comment=None
            )
            client_user = db.get_user_by_id(client_user_id)
            client_user_dict = dict(client_user) if client_user else {}
            target_name = client_user_dict.get('first_name', 'Клиент')
            target_role = "клиента"
            return_callback = "worker_my_orders"
            return_menu_callback = "show_worker_menu"
            notify_user_id = client_user_id
            notify_text_prefix = "Мастер завершил заказ и оставил вам оценку"

        if not review_saved:
            await safe_edit_message(
                query,
                "❌ Не удалось сохранить отзыв. Возможно, вы уже оценили этот заказ.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад к заказам", callback_data=return_callback)
                ]])
            )
            return

        # Обновляем статус заказа на "done" (только если ещё не done)
        if order_dict['status'] != 'done':
            db.update_order_status(order_id, 'done')

        # Уведомляем противоположную сторону
        try:
            notify_user = db.get_user_by_id(notify_user_id)
            if notify_user:
                notify_user_dict = dict(notify_user)
                stars = "⭐" * rating

                # Если клиент оценил мастера - предлагаем загрузить фото
                if is_client:
                    keyboard = [
                        [InlineKeyboardButton("📸 Загрузить фото работы", callback_data=f"upload_work_photo_{order_id}")],
                        [InlineKeyboardButton("➡️ Пропустить", callback_data=f"skip_work_photo_{order_id}")]
                    ]
                    extra_text = (
                        f"\n\n📸 <b>Загрузите фото выполненной работы:</b>\n"
                        f"• Это повысит доверие будущих клиентов\n"
                        f"• Фото будут видны в вашем профиле\n"
                        f"• Клиент сможет подтвердить подлинность фото\n"
                        f"• Подтверждённые фото получат специальный значок ✅"
                    )
                else:
                    keyboard = None
                    extra_text = "\n\nСпасибо за ваш заказ!"

                await context.bot.send_message(
                    chat_id=notify_user_dict['telegram_id'],
                    text=(
                        f"✅ <b>Заказ #{order_id} завершен!</b>\n\n"
                        f"{notify_text_prefix}:\n"
                        f"{stars} ({rating}/5)\n\n"
                        f"🎉 Поздравляем с успешным {'выполнением работы' if is_client else 'заказом'}!"
                        f"{extra_text}"
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление пользователю {notify_user_id}: {e}")

        # Показываем сообщение об успехе
        stars = "⭐" * rating
        text = (
            f"✅ <b>Заказ завершен!</b>\n\n"
            f"Спасибо за вашу оценку: {stars} ({rating}/5)\n\n"
            f"👤 <b>{target_role.capitalize()}:</b> {target_name}\n\n"
            f"💬 Хотите оставить комментарий к отзыву?"
        )

        keyboard = [
            [InlineKeyboardButton("💬 Оставить комментарий", callback_data=f"add_comment_{order_id}")],
            [InlineKeyboardButton("📂 Мои заказы", callback_data=return_callback)],
            [InlineKeyboardButton("🏠 Главное меню", callback_data=return_menu_callback)]
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        logger.info(f"{'Клиент' if is_client else 'Мастер'} {user_dict['id']} завершил заказ {order_id} с оценкой {rating}")

    except Exception as e:
        logger.error(f"Ошибка при сохранении оценки заказа: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка при сохранении оценки:\n{str(e)}",
            parse_mode="HTML"
        )


async def worker_upload_work_photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Начало загрузки фото завершённой работы мастером.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем order_id из callback_data
        order_id = int(query.data.replace("upload_work_photo_", ""))

        # Сохраняем order_id в context для последующей загрузки фото
        context.user_data['uploading_work_photo_order_id'] = order_id

        text = (
            f"📸 <b>Загрузка фото работы для заказа #{order_id}</b>\n\n"
            f"Отправьте фотографии выполненной работы (до 10 фото).\n\n"
            f"💡 <b>Советы для качественных фото:</b>\n"
            f"• Убедитесь, что работа хорошо видна\n"
            f"• Используйте хорошее освещение\n"
            f"• Покажите результат с разных ракурсов\n"
            f"• Избегайте размытых фото\n\n"
            f"После загрузки всех фото нажмите «Завершить»."
        )

        keyboard = [
            [InlineKeyboardButton("✅ Завершить загрузку", callback_data=f"finish_work_photos_{order_id}")],
            [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_work_photos_{order_id}")]
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Инициализируем список загруженных фото
        context.user_data['uploaded_work_photos'] = []

        logger.info(f"Мастер начал загрузку фото для заказа {order_id}")

    except Exception as e:
        logger.error(f"Ошибка при начале загрузки фото работы: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def worker_skip_work_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Пропуск загрузки фото работы.
    """
    query = update.callback_query
    await query.answer()

    try:
        order_id = int(query.data.replace("skip_work_photo_", ""))

        await safe_edit_message(
            query,
            "✅ Фото работы можно добавить позже через профиль.\n\n"
            "Спасибо за работу!",
            parse_mode="HTML"
        )

        logger.info(f"Мастер пропустил загрузку фото для заказа {order_id}")

    except Exception as e:
        logger.error(f"Ошибка при пропуске загрузки фото: {e}", exc_info=True)


async def worker_upload_work_photo_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Получение фото завершённой работы от мастера.
    """
    try:
        # Проверяем, что идёт процесс загрузки фото работы
        order_id = context.user_data.get('uploading_work_photo_order_id')
        if not order_id:
            return  # Игнорируем фото, если не в процессе загрузки

        # Получаем file_id фото
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id  # Берём фото максимального размера

            # Добавляем в список загруженных
            if 'uploaded_work_photos' not in context.user_data:
                context.user_data['uploaded_work_photos'] = []

            context.user_data['uploaded_work_photos'].append(photo_id)
            count = len(context.user_data['uploaded_work_photos'])

            # Подтверждаем получение
            await update.message.reply_text(
                f"✅ Фото {count} получено.\n\n"
                f"Можете отправить ещё фото или нажмите «Завершить загрузку».",
                parse_mode="HTML"
            )

            logger.info(f"Получено фото {count} для заказа {order_id}")

    except Exception as e:
        logger.error(f"Ошибка при получении фото работы: {e}", exc_info=True)


async def worker_finish_work_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Завершение загрузки фото работы и сохранение в БД.
    """
    query = update.callback_query
    await query.answer()

    try:
        order_id = int(query.data.replace("finish_work_photos_", ""))
        photos = context.user_data.get('uploaded_work_photos', [])

        if not photos:
            await safe_edit_message(
                query,
                "❌ Вы не загрузили ни одного фото.\n\n"
                "Нажмите «Загрузить фото работы» чтобы попробовать снова.",
                parse_mode="HTML"
            )
            return

        # Получаем информацию о мастере
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict["id"])
        if not worker_profile:
            await safe_edit_message(query, "❌ Профиль мастера не найден.")
            return

        worker_dict = dict(worker_profile)

        # Сохраняем каждое фото в БД
        saved_count = 0
        for photo_id in photos:
            result = db.add_completed_work_photo(order_id, worker_dict['id'], photo_id)
            if result:
                saved_count += 1

        # Получаем заказ для уведомления клиента
        order = db.get_order_by_id(order_id)
        if order:
            order_dict = dict(order)
            client = db.get_client_by_id(order_dict['client_id'])
            if client:
                client_dict = dict(client)
                client_user = db.get_user_by_id(client_dict['user_id'])
                if client_user:
                    client_user_dict = dict(client_user)

                    # Уведомляем клиента о загруженных фото
                    keyboard = [
                        [InlineKeyboardButton("📸 Проверить фото", callback_data=f"check_work_photos_{order_id}")],
                        [InlineKeyboardButton("➡️ Позже", callback_data="noop")]
                    ]

                    try:
                        await context.bot.send_message(
                            chat_id=client_user_dict['telegram_id'],
                            text=(
                                f"📸 <b>Мастер загрузил фото работы!</b>\n\n"
                                f"По заказу #{order_id} мастер <b>{worker_dict.get('name', 'Мастер')}</b> "
                                f"загрузил {saved_count} {_get_photos_word(saved_count)} выполненной работы.\n\n"
                                f"✅ <b>Подтвердите фотографии:</b>\n"
                                f"Если это действительно фото вашего заказа, подтвердите их. "
                                f"Подтверждённые фото получат специальный значок ✅ и будут показаны в профиле мастера."
                            ),
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить клиента о фото: {e}")

        # Подтверждаем мастеру
        await safe_edit_message(
            query,
            f"✅ <b>Фотографии загружены!</b>\n\n"
            f"Загружено {saved_count} {_get_photos_word(saved_count)}.\n\n"
            f"📨 Клиент получил уведомление и сможет подтвердить подлинность фото.\n"
            f"Подтверждённые фото будут отмечены значком ✅ в вашем профиле.",
            parse_mode="HTML"
        )

        # Очищаем context
        context.user_data.pop('uploading_work_photo_order_id', None)
        context.user_data.pop('uploaded_work_photos', None)

        logger.info(f"Мастер {worker_dict['id']} загрузил {saved_count} фото для заказа {order_id}")

    except Exception as e:
        logger.error(f"Ошибка при завершении загрузки фото: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка при сохранении фото:\n{str(e)}",
            parse_mode="HTML"
        )


async def worker_cancel_work_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Отмена загрузки фото работы.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Очищаем context
        context.user_data.pop('uploading_work_photo_order_id', None)
        context.user_data.pop('uploaded_work_photos', None)

        await safe_edit_message(
            query,
            "❌ Загрузка фото отменена.\n\n"
            "Вы сможете добавить фото позже через профиль.",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при отмене загрузки фото: {e}", exc_info=True)


async def client_check_work_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Просмотр фото работы клиентом для подтверждения.
    """
    query = update.callback_query
    await query.answer()

    try:
        order_id = int(query.data.replace("check_work_photos_", ""))

        # Получаем фото работы
        photos = db.get_completed_work_photos(order_id)
        if not photos:
            await safe_edit_message(
                query,
                "❌ Фотографии не найдены.",
                parse_mode="HTML"
            )
            return

        # Отправляем фото с кнопками подтверждения
        text = (
            f"📸 <b>Фотографии работы по заказу #{order_id}</b>\n\n"
            f"Всего фото: {len(photos)}\n\n"
            f"Подтвердите, что это фото вашего заказа:"
        )

        for idx, photo in enumerate(photos):
            photo_dict = dict(photo)
            status = "✅ Подтверждено" if photo_dict['verified'] else "⏳ Ожидает подтверждения"

            keyboard = []
            if not photo_dict['verified']:
                keyboard.append([InlineKeyboardButton(
                    f"✅ Подтвердить фото #{idx+1}",
                    callback_data=f"verify_photo_{photo_dict['id']}"
                )])

            try:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=photo_dict['photo_id'],
                    caption=f"Фото #{idx+1} - {status}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке фото: {e}")

        await query.message.delete()

    except Exception as e:
        logger.error(f"Ошибка при просмотре фото работы: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def client_verify_work_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Подтверждение фото работы клиентом.
    """
    query = update.callback_query
    await query.answer("✅ Фото подтверждено!")

    try:
        photo_id = int(query.data.replace("verify_photo_", ""))

        # Подтверждаем фото в БД
        success = db.verify_completed_work_photo(photo_id)

        if success:
            await query.edit_message_caption(
                caption="✅ <b>Фото подтверждено клиентом</b>\n\n"
                        "Это фото теперь будет отображаться в профиле мастера с отметкой о подтверждении.",
                parse_mode="HTML"
            )
            logger.info(f"Клиент подтвердил фото {photo_id}")
        else:
            await query.answer("❌ Ошибка при подтверждении фото", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка при подтверждении фото: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка", show_alert=True)


def _get_photos_word(count):
    """Вспомогательная функция для склонения слова 'фото'"""
    if count % 10 == 1 and count % 100 != 11:
        return "фото"
    elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
        return "фото"
    else:
        return "фото"


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
        order = db.get_order_by_id(order_id)
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
        price = selected_bid['proposed_price']
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
    """Оплата картой через внешний платежный сервис (MOCK для демонстрации)"""
    query = update.callback_query
    await query.answer()

    try:
        bid_id = int(query.data.replace("pay_card_", ""))

        # MOCK: В реальной системе здесь будет интеграция с BePaid/Stripe
        # Для демонстрации показываем реквизиты и кнопку подтверждения

        text = (
            "💳 <b>Оплата банковской картой</b>\n\n"
            "💰 <b>Сумма к оплате: 1.00 BYN</b>\n\n"
            "📋 <b>Реквизиты для оплаты:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💳 Карта: <code>4242 4242 4242 4242</code>\n"
            "👤 Получатель: <b>ИП Ремонтные Услуги</b>\n"
            "📝 Назначение: <i>Доступ к контакту мастера</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ <b>ДЕМО-РЕЖИМ:</b> Это тестовая заглушка.\n"
            "В продакшн будет интеграция с:\n"
            "• <b>BePaid</b> (для клиентов из Беларуси)\n"
            "• <b>Stripe</b> (международные платежи)\n\n"
            "💡 Нажмите кнопку ниже для имитации оплаты:"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Я оплатил", callback_data=f"confirm_payment_{bid_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"select_master_{bid_id}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в pay_with_card: {e}", exc_info=True)


async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Подтверждение оплаты клиентом (MOCK для демонстрации).
    В реальной системе здесь будет проверка статуса платежа через API платежного провайдера.
    """
    query = update.callback_query
    await query.answer("Проверяем оплату...")

    try:
        bid_id = int(query.data.replace("confirm_payment_", ""))

        # MOCK: Показываем процесс проверки
        await query.edit_message_text(
            "⏳ <b>Проверяем оплату...</b>\n\n"
            "Подождите, идет проверка платежа...",
            parse_mode="HTML"
        )

        # MOCK: В реальной системе здесь был бы запрос к платежному API
        # Например: payment_status = await check_payment_status(transaction_id)
        # Для демонстрации просто имитируем успешную оплату

        # Небольшая задержка для реалистичности (опционально)
        import asyncio
        await asyncio.sleep(1)

        # Показываем успешную оплату
        await query.edit_message_text(
            "✅ <b>Оплата подтверждена!</b>\n\n"
            "💳 Списано: <b>1.00 BYN</b>\n"
            "📄 ID транзакции: <code>MOCK-" + str(bid_id).zfill(6) + "</code>\n\n"
            "⏳ Открываем доступ к мастеру...",
            parse_mode="HTML"
        )

        # Еще небольшая задержка
        await asyncio.sleep(1)

        # Вызываем основную функцию успешной оплаты
        # Подменяем callback_data чтобы test_payment_success правильно обработал
        query.data = f"test_payment_success_{bid_id}"
        await test_payment_success(update, context)

    except Exception as e:
        logger.error(f"Ошибка в confirm_payment: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ <b>Ошибка при проверке оплаты</b>\n\n"
            f"Произошла ошибка: {str(e)}\n\n"
            "Попробуйте еще раз или обратитесь в поддержку.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Попробовать еще раз", callback_data=f"pay_card_{bid_id}"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="show_client_menu")
            ]])
        )


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

        # 1. Создаём транзакцию (оплата 1 BYN за доступ)
        # ИСПРАВЛЕНО: Было 5.00, изменено на 1.00 для соответствия UI
        transaction_id = db.create_transaction(
            user_id=user["id"],
            order_id=order_id,
            bid_id=bid_id,
            transaction_type="chat_access",  # ИСПРАВЛЕНО: точное название (не contact, а chat)
            amount=1.00,  # ИСПРАВЛЕНО: было 5.00
            currency="BYN",
            payment_method="test",
            description=f"Доступ к чату с мастером для заказа #{order_id}"  # ИСПРАВЛЕНО: было "к мастеру"
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

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в open_chat: {e}", exc_info=True)
        await safe_edit_message(query, f"❌ Ошибка при открытии чата:\n{str(e)}")


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
    """
    ИСПРАВЛЕНО: Полная отмена любого активного диалога с возвратом в главное меню.
    """
    context.user_data.clear()

    keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu_fresh")]]

    await update.message.reply_text(
        "❌ Действие отменено.\n\n"
        "Возвращаемся в главное меню...",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END


async def cancel_from_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРИТИЧЕСКИ ВАЖНО: Обработка /start во время ConversationHandler.

    Позволяет пользователю выйти из застрявшего диалога.
    """
    context.user_data.clear()
    logger.info(f"User {update.effective_user.id} cancelled conversation via /start")

    # Вызываем обычный start_command для показа меню
    return await start_command(update, context)


async def cancel_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРИТИЧЕСКИ ВАЖНО: Обработка кнопок меню во время ConversationHandler.

    Позволяет пользователю выйти из застрявшего диалога через кнопки меню.
    Исправляет баг, когда бот зависал после ошибки при загрузке фото.
    """
    query = update.callback_query
    await query.answer()

    context.user_data.clear()
    logger.info(f"User {query.from_user.id} cancelled conversation via callback: {query.data}")

    # Перенаправляем на соответствующий обработчик меню
    if query.data == "go_main_menu":
        return await go_main_menu(update, context)
    elif query.data == "show_worker_menu":
        return await show_worker_menu(update, context)
    elif query.data == "show_client_menu":
        return await show_client_menu(update, context)

    # По умолчанию возвращаемся в главное меню
    return await go_main_menu(update, context)


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

        # ИСПРАВЛЕНО: Один запрос для всех категорий вместо N запросов
        # Раньше: 5 категорий = 5 SQL запросов
        # Теперь: 5 категорий = 1 SQL запрос
        all_orders = db.get_orders_by_categories(categories, per_page=30)
        all_orders = [dict(order) for order in all_orders]
        
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

        await safe_edit_message(
            query,
            orders_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре заказов: {e}", exc_info=True)
        await safe_edit_message(
            query,
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

        # ПРОВЕРКА: Мастер не может откликаться на свой заказ
        client = db.get_client_by_id(order_dict['client_id'])
        is_own_order = False
        if client:
            client_dict = dict(client)
            is_own_order = (client_dict['user_id'] == user["id"])
        
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
                if is_own_order:
                    keyboard.append([InlineKeyboardButton("🚫 Это ваш заказ", callback_data="noop")])
                elif already_bid:
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
                if is_own_order:
                    keyboard.append([InlineKeyboardButton("🚫 Это ваш заказ", callback_data="noop")])
                elif already_bid:
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

        # ПРОВЕРКА: Мастер не может откликаться на свой заказ
        client = db.get_client_by_id(order_dict['client_id'])
        is_own_order = False
        if client:
            client_dict = dict(client)
            is_own_order = (client_dict['user_id'] == user["id"])

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
        
        if is_own_order:
            keyboard.append([InlineKeyboardButton("🚫 Это ваш заказ", callback_data="noop")])
        elif already_bid:
            keyboard.append([InlineKeyboardButton("✅ Вы уже откликнулись", callback_data="noop")])
        else:
            keyboard.append([InlineKeyboardButton("💰 Откликнуться", callback_data=f"bid_on_order_{order_id}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ К списку заказов", callback_data="worker_view_orders")])

        # Обновляем фото
        await query.message.edit_media(
            media=InputMediaPhoto(media=photo_ids[current_index], caption=text, parse_mode="HTML"),
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
    """Начало создания отклика - выбор валюты"""
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

    # ПРОВЕРКА: Мастер не может откликаться на свой заказ
    order = db.get_order_by_id(order_id)
    if order:
        order_dict = dict(order)
        client = db.get_client_by_id(order_dict['client_id'])
        if client:
            client_dict = dict(client)
            if client_dict['user_id'] == user_dict.get("id"):
                await query.answer("❌ Вы не можете откликнуться на свой заказ!", show_alert=True)
                return ConversationHandler.END

    if db.check_worker_bid_exists(order_id, worker_id):
        await query.answer("Вы уже откликнулись на этот заказ!", show_alert=True)
        return ConversationHandler.END

    text = (
        "💰 <b>Ваш отклик на заказ</b>\n\n"
        "⚠️ <b>ВНИМАНИЕ:</b> Цену изменить будет НЕЛЬЗЯ!\n\n"
        "💵 Сначала выберите валюту, в которой будете указывать цену:"
    )

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

    # Пробуем отредактировать как caption (если есть фото), иначе как text
    try:
        await query.edit_message_caption(
            caption=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except:
        # Если не получилось (нет фото), редактируем текст
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    return BID_SELECT_CURRENCY


async def worker_bid_enter_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода цены - переход к комментарию"""
    price_text = update.message.text.strip()

    # Проверяем что это число
    try:
        price = float(price_text.replace(',', '.'))
        if price <= 0:
            raise ValueError
    except:
        currency = context.user_data.get('bid_currency', 'BYN')
        await update.message.reply_text(
            f"❌ Пожалуйста, введите корректную цену в {currency} (только число).\n\n"
            "Например: <code>150</code> или <code>99.50</code>",
            parse_mode="HTML"
        )
        return BID_ENTER_PRICE

    context.user_data['bid_price'] = price
    currency = context.user_data.get('bid_currency', 'BYN')

    # Спрашиваем комментарий
    await update.message.reply_text(
        f"💰 Ваша цена: <b>{price} {currency}</b>\n\n"
        "📝 Хотите добавить комментарий к отклику?\n\n"
        "💡 <b>Это ваш шанс выделиться!</b> Расскажите:\n"
        "✓ Почему именно такая цена (материалы, сложность работ)\n"
        "✓ Что входит в стоимость, а что оплачивается отдельно\n"
        "✓ Когда можете приступить к работе\n"
        "✓ Ваш опыт в подобных проектах\n\n"
        "<b>Примеры:</b>\n"
        "• «Цена с моими материалами. Могу начать завтра. Делал 20+ таких объектов»\n"
        "• «В стоимость входит работа и расходники. Выезд бесплатный. Опыт 8 лет»\n"
        "• «Цена за работу, материалы оплачиваете отдельно. Гарантия 2 года»\n\n"
        "Напишите комментарий или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Пропустить", callback_data="bid_skip_comment"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_bid")
        ]])
    )

    return BID_ENTER_COMMENT


async def worker_bid_select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора валюты - переход к вводу цены"""
    query = update.callback_query
    await query.answer()

    currency = query.data.replace("bid_currency_", "")
    context.user_data['bid_currency'] = currency

    # Получаем символ валюты для отображения
    currency_symbols = {
        'BYN': '₽',
        'USD': '$',
        'EUR': '€'
    }
    currency_symbol = currency_symbols.get(currency, currency)

    # Спрашиваем цену в выбранной валюте
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_bid")
    ]])

    await query.edit_message_text(
        f"💰 <b>Валюта выбрана: {currency} ({currency_symbol})</b>\n\n"
        f"Теперь введите вашу цену в {currency} (только число):\n\n"
        "Например: <code>150</code> или <code>99.50</code>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

    return BID_ENTER_PRICE


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
        if update.callback_query:
            telegram_id = update.callback_query.from_user.id
            message = update.callback_query.message
        else:
            telegram_id = update.effective_user.id
            message = update.message
        
        user = db.get_user(telegram_id)
        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict["id"])
        worker_profile_dict = dict(worker_profile)

        # Создаём отклик (может вызвать ValueError при rate limiting)
        try:
            bid_id = db.create_bid(
                order_id=order_id,
                worker_id=worker_profile_dict["id"],
                proposed_price=price,
                currency=currency,
                comment=comment
            )
        except ValueError as e:
            # Rate limiting error
            if update.callback_query:
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

        logger.info(f"✅ Отклик #{bid_id} создан мастером {worker_profile_dict['id']} на заказ {order_id}")

        # Отправляем уведомление клиенту
        order = db.get_order_by_id(order_id)
        if order:
            # Получаем telegram_id клиента
            client = db.get_client_by_id(order['client_id'])
            client_user = db.get_user_by_id(client['user_id'])

            worker_name = worker_profile_dict.get('name', 'Мастер')

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

        if update.callback_query:
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

    # Удаляем старое сообщение и отправляем новое
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=message,
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
    """Начало создания заказа - выбор региона"""
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

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"orderregion_{region_name}"
        )])

    await query.edit_message_text(
        "📝 <b>Создание заказа</b>\n\n"
        "🏙 <b>Шаг 1:</b> Где нужна работа? Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CREATE_ORDER_REGION_SELECT


async def create_order_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора региона для заказа"""
    query = update.callback_query
    await query.answer()

    region = query.data.replace("orderregion_", "")
    region_data = BELARUS_REGIONS.get(region)

    if not region_data:
        await query.edit_message_text("❌ Ошибка выбора региона. Попробуйте снова.")
        return CREATE_ORDER_REGION_SELECT

    context.user_data["order_region"] = region

    # Если выбран Минск или "Вся Беларусь" - сохраняем и переходим к выбору категорий
    if region_data["type"] in ["city", "country"]:
        context.user_data["order_city"] = region

        # Переходим к выбору категорий
        keyboard = []
        for cat_id, category_data in WORK_CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(
                category_data["name"],
                callback_data=f"order_maincat_{cat_id}"
            )])

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_order_back_to_region")])

        await query.edit_message_text(
            f"🏙 Город: {region_data['display']}\n\n"
            "🔧 <b>Шаг 2:</b> Выберите основную категорию работ:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_ORDER_MAIN_CATEGORY

    # Если выбрана область - показываем города
    else:
        cities = region_data.get("cities", [])
        keyboard = []
        row = []
        for city in cities:
            row.append(InlineKeyboardButton(city, callback_data=f"ordercity_{city}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Добавляем кнопку "Другой город в области"
        keyboard.append([InlineKeyboardButton(
            f"📍 Другой город в области",
            callback_data="ordercity_other"
        )])

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_order_back_to_region")])

        await query.edit_message_text(
            f"📍 Область: {region_data['display']}\n\n"
            "🏙 Выберите город:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_ORDER_CITY


async def create_order_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города для заказа"""
    query = update.callback_query
    await query.answer()

    city = query.data.replace("ordercity_", "")

    if city == "other":
        await query.edit_message_text(
            "🏙 Напишите название города:"
        )
        return CREATE_ORDER_CITY
    else:
        context.user_data["order_city"] = city

        # Переходим к выбору основной категории
        keyboard = []
        for cat_id, category_data in WORK_CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(
                category_data["name"],
                callback_data=f"order_maincat_{cat_id}"
            )])

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_order_back_to_city")])

        await query.edit_message_text(
            f"🏙 Город: <b>{city}</b>\n\n"
            "🔧 <b>Шаг 2:</b> Выберите основную категорию работ:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_ORDER_MAIN_CATEGORY


async def create_order_main_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора основной категории для заказа"""
    query = update.callback_query
    await query.answer()

    cat_id = query.data.replace("order_maincat_", "")
    category_name = WORK_CATEGORIES[cat_id]["name"]
    context.user_data["order_main_category"] = cat_id

    # Получаем подкатегории для выбранной категории
    subcategories = WORK_CATEGORIES[cat_id]["subcategories"]

    # Создаем кнопки подкатегорий (2 в ряд)
    keyboard = []
    row = []
    for idx, subcat in enumerate(subcategories):
        row.append(InlineKeyboardButton(subcat, callback_data=f"order_subcat_{cat_id}:{idx}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Добавляем кнопку "Назад"
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_order_back_to_maincat")])

    city = context.user_data.get("order_city", "")
    emoji = WORK_CATEGORIES[cat_id]["emoji"]

    await query.edit_message_text(
        f"🏙 Город: {city}\n"
        f"{emoji} Категория: {category_name}\n\n"
        "🔧 <b>Шаг 3:</b> Выберите подкатегорию работ:\n\n"
        "Выберите одну подкатегорию, которая наиболее точно описывает ваш заказ.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CREATE_ORDER_SUBCATEGORY_SELECT


async def create_order_subcategory_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора подкатегории для заказа"""
    query = update.callback_query
    await query.answer()

    # Парсим cat_id:index из callback_data
    selected = query.data.replace("order_subcat_", "")
    cat_id, idx_str = selected.split(":")
    idx = int(idx_str)
    subcategory = WORK_CATEGORIES[cat_id]["subcategories"][idx]

    context.user_data["order_category"] = subcategory

    # Переходим к описанию
    main_category_name = WORK_CATEGORIES[cat_id]["name"]
    await query.edit_message_text(
        f"Город: <b>{context.user_data['order_city']}</b>\n"
        f"Категория: <b>{main_category_name} → {subcategory}</b>\n\n"
        "📝 <b>Шаг 4:</b> Опишите что нужно сделать\n\n"
        "💡 <b>Важно!</b> Мастера будут предлагать свою цену за услуги, поэтому укажите:\n"
        "✓ Объём работ (сколько розеток, метраж, количество)\n"
        "✓ Размеры и особенности (толщина стен, высота потолков)\n"
        "✓ Материалы (есть свои или нужна закупка)\n"
        "✓ Состояние объекта (старая проводка, новострой и т.д.)\n\n"
        "Пример:\n"
        "• Заменить 5 розеток в бетонных стенах (материалы куплены)\n"
        "• Установить смеситель Grohe на кухне (есть в наличии)\n"
        "• Повесить люстру весом 8кг, высота потолка 3м\n\n"
        "Чем точнее описание - тем точнее цена и меньше недопониманий!",
        parse_mode="HTML"
    )
    return CREATE_ORDER_DESCRIPTION




async def create_order_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка описания заказа"""
    description = update.message.text.strip()
    
    if len(description) < 10:
        await update.message.reply_text(
            "⚠️ Опишите подробнее (минимум 10 символов)"
        )
        return CREATE_ORDER_DESCRIPTION
    
    context.user_data["order_description"] = description

    # Предлагаем загрузить фото и видео
    keyboard = [[InlineKeyboardButton("⏭ Пропустить", callback_data="order_skip_photos")]]

    await update.message.reply_text(
        "📸 <b>Шаг 4:</b> Загрузите фото или видео объекта\n\n"
        "📷 Фото: до 10 штук\n"
        "🎥 Видео: до 3 штук (макс. 50 МБ каждое)\n\n"
        "Фото и видео помогут мастеру точнее оценить работу и сделать правильное предложение.\n\n"
        "Когда закончите загрузку, отправьте команду /done или нажмите кнопку ниже.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    context.user_data["order_photos"] = []
    context.user_data["order_videos"] = []
    return CREATE_ORDER_PHOTOS


async def create_order_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загрузки фото и видео для заказа"""

    if "order_photos" not in context.user_data:
        context.user_data["order_photos"] = []
    if "order_videos" not in context.user_data:
        context.user_data["order_videos"] = []

    photos = context.user_data["order_photos"]
    videos = context.user_data["order_videos"]

    # Обработка фото
    if update.message.photo:
        if len(photos) >= 10:
            await update.message.reply_text(
                "⚠️ Максимум 10 фото.\n\nМожете добавить видео или завершить командой /done"
            )
            return CREATE_ORDER_PHOTOS

        # Получаем file_id
        file_id = update.message.photo[-1].file_id

        # КРИТИЧНО: Валидация file_id
        if not validate_file_id(file_id):
            logger.error(f"❌ Невалидный file_id при загрузке фото заказа: {file_id}")
            keyboard = [[InlineKeyboardButton("✅ Завершить и опубликовать", callback_data="order_publish")]]
            await update.message.reply_text(
                "❌ Ошибка при обработке фото.\n\n"
                "Попробуйте отправить фото еще раз или используйте другое изображение.\n\n"
                "Или завершите создание заказа без этого фото.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CREATE_ORDER_PHOTOS

        # Сохраняем file_id
        photos.append(file_id)

        keyboard = [[InlineKeyboardButton("✅ Завершить и опубликовать", callback_data="order_publish")]]

        await update.message.reply_text(
            f"✅ Фото {len(photos)}/10 добавлено!\n\n"
            f"📷 Фото: {len(photos)}/10\n"
            f"🎥 Видео: {len(videos)}/3\n\n"
            f"Можете добавить ещё или завершить командой /done",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return CREATE_ORDER_PHOTOS

    # Обработка видео
    elif update.message.video:
        if len(videos) >= 3:
            await update.message.reply_text(
                "⚠️ Максимум 3 видео.\n\nМожете добавить фото или завершить командой /done"
            )
            return CREATE_ORDER_PHOTOS

        # Проверка размера видео (50 МБ = 50 * 1024 * 1024 байт)
        video_size = update.message.video.file_size
        max_size = 50 * 1024 * 1024

        if video_size > max_size:
            await update.message.reply_text(
                f"⚠️ Видео слишком большое ({video_size / 1024 / 1024:.1f} МБ).\n"
                f"Максимальный размер: 50 МБ.\n\n"
                f"Попробуйте сжать видео или отправьте другое."
            )
            return CREATE_ORDER_PHOTOS

        # Получаем file_id
        file_id = update.message.video.file_id

        # КРИТИЧНО: Валидация file_id
        if not validate_file_id(file_id):
            logger.error(f"❌ Невалидный file_id при загрузке видео заказа: {file_id}")
            keyboard = [[InlineKeyboardButton("✅ Завершить и опубликовать", callback_data="order_publish")]]
            await update.message.reply_text(
                "❌ Ошибка при обработке видео.\n\n"
                "Попробуйте отправить видео еще раз или используйте другой файл.\n\n"
                "Или завершите создание заказа без этого видео.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CREATE_ORDER_PHOTOS

        # Сохраняем file_id
        videos.append(file_id)

        keyboard = [[InlineKeyboardButton("✅ Завершить и опубликовать", callback_data="order_publish")]]

        await update.message.reply_text(
            f"✅ Видео {len(videos)}/3 добавлено!\n\n"
            f"📷 Фото: {len(photos)}/10\n"
            f"🎥 Видео: {len(videos)}/3\n\n"
            f"Можете добавить ещё или завершить командой /done",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return CREATE_ORDER_PHOTOS

    return CREATE_ORDER_PHOTOS


async def create_order_done_uploading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение загрузки фото и видео по команде /done"""
    return await create_order_publish(update, context)


async def create_order_skip_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск загрузки фото и видео"""
    query = update.callback_query
    await query.answer()

    context.user_data["order_photos"] = []
    context.user_data["order_videos"] = []

    return await create_order_publish(update, context)




# ------- ОБРАБОТЧИКИ КНОПОК "НАЗАД" ДЛЯ СОЗДАНИЯ ЗАКАЗА -------

async def create_order_back_to_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору региона"""
    query = update.callback_query
    await query.answer()

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"orderregion_{region_name}"
        )])

    await query.edit_message_text(
        "📝 <b>Создание заказа</b>\n\n"
        "🏙 <b>Шаг 1:</b> Где нужна работа? Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CREATE_ORDER_REGION_SELECT


async def create_order_back_to_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору города"""
    query = update.callback_query
    await query.answer()

    region = context.user_data.get("order_region")
    if not region:
        # Если региона нет, возвращаемся к выбору региона
        return await create_order_back_to_region(update, context)

    region_data = BELARUS_REGIONS.get(region)
    if not region_data:
        return await create_order_back_to_region(update, context)

    # Если это был Минск или Вся Беларусь - возвращаемся к выбору региона
    if region_data["type"] in ["city", "country"]:
        return await create_order_back_to_region(update, context)

    # Показываем города области
    cities = region_data.get("cities", [])
    keyboard = []
    row = []
    for city in cities:
        row.append(InlineKeyboardButton(city, callback_data=f"ordercity_{city}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(
        f"📍 Другой город в области",
        callback_data="ordercity_other"
    )])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_order_back_to_region")])

    await query.edit_message_text(
        f"📍 Область: {region_data['display']}\n\n"
        "🏙 Выберите город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CREATE_ORDER_CITY


async def create_order_back_to_maincat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору основной категории"""
    query = update.callback_query
    await query.answer()

    city = context.user_data.get("order_city", "")

    keyboard = []
    for cat_id, category_data in WORK_CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(
            category_data["name"],
            callback_data=f"order_maincat_{cat_id}"
        )])

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_order_back_to_city")])

    await query.edit_message_text(
        f"🏙 Город: <b>{city}</b>\n\n"
        "🔧 <b>Шаг 2:</b> Выберите основную категорию работ:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CREATE_ORDER_MAIN_CATEGORY


async def create_order_city_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода города вручную при создании заказа"""
    if update.callback_query:
        # Это callback от кнопки "Другой город"
        return CREATE_ORDER_CITY  # Ожидаем текстовое сообщение
    else:
        # Это текстовое сообщение с названием города
        city = update.message.text.strip()
        context.user_data["order_city"] = city

        # Переходим к выбору категорий
        keyboard = []
        for cat_id, category_data in WORK_CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(
                category_data["name"],
                callback_data=f"order_maincat_{cat_id}"
            )])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_order_back_to_city")])

        await update.message.reply_text(
            f"🏙 Город: <b>{city}</b>\n\n"
            "🔧 <b>Шаг 2:</b> Выберите основную категорию работ:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_ORDER_MAIN_CATEGORY



async def create_order_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Публикация заказа.
    ИСПРАВЛЕНО: Валидация обязательных полей перед созданием.
    """

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message = query.message
    else:
        message = update.message

    # КРИТИЧНО: Проверяем наличие всех обязательных полей
    required_fields = ["order_client_id", "order_city", "order_category", "order_description"]
    ok, missing = validate_required_fields(context, required_fields)

    if not ok:
        logger.error(f"Missing required fields in create_order: {missing}")
        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main_menu")]]
        await message.reply_text(
            "❌ Ошибка: недостаточно данных для создания заказа.\n\n"
            "Пожалуйста, начните создание заказа заново.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        logger.info("=== Публикация заказа ===")
        logger.info(f"client_id: {context.user_data.get('order_client_id')}")
        logger.info(f"city: {context.user_data.get('order_city')}")
        logger.info(f"category: {context.user_data.get('order_category')}")
        logger.info(f"description: {context.user_data.get('order_description')}")
        logger.info(f"photos: {len(context.user_data.get('order_photos', []))}")
        logger.info(f"videos: {len(context.user_data.get('order_videos', []))}")

        # КРИТИЧНО: Валидация file_id перед сохранением заказа
        order_photos = context.user_data.get("order_photos", [])
        valid_order_photos = [fid for fid in order_photos if validate_file_id(fid)]
        if len(valid_order_photos) < len(order_photos):
            removed_count = len(order_photos) - len(valid_order_photos)
            logger.warning(f"⚠️ Удалено {removed_count} невалидных file_id из фото заказа")

        # Валидация file_id для видео
        order_videos = context.user_data.get("order_videos", [])
        valid_order_videos = [fid for fid in order_videos if validate_file_id(fid)]
        if len(valid_order_videos) < len(order_videos):
            removed_count = len(order_videos) - len(valid_order_videos)
            logger.warning(f"⚠️ Удалено {removed_count} невалидных file_id из видео заказа")

        # Создаём заказ в БД (может вызвать ValueError при rate limiting)
        try:
            order_id = db.create_order(
                client_id=context.user_data["order_client_id"],
                city=context.user_data["order_city"],
                categories=context.user_data["order_category"],
                description=context.user_data["order_description"],
                photos=valid_order_photos,
                videos=valid_order_videos
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

            # Находим всех мастеров в нужной категории И городе и отправляем уведомления
            order_city = context.user_data['order_city']
            category = context.user_data["order_category"]

            # ВАЖНО: фильтруем мастеров по городу И категории
            workers = db.get_all_workers(city=order_city, category=category)
            for worker in workers:
                worker_dict = dict(worker)

                worker_user = db.get_user_by_id(worker_dict['user_id'])
                if worker_user:
                    # Проверяем включены ли уведомления у мастера
                    if db.are_notifications_enabled(worker_dict['user_id']):
                        await notify_worker_new_order(
                            context,
                            worker_user['telegram_id'],
                            order_dict
                        )

        categories_text = context.user_data["order_category"]
        photos_count = len(context.user_data.get("order_photos", []))
        videos_count = len(context.user_data.get("order_videos", []))

        keyboard = [
            [InlineKeyboardButton("📂 Мои заказы", callback_data="client_my_orders")],
            [InlineKeyboardButton("⬅️ В меню", callback_data="show_client_menu")],
        ]

        media_info = ""
        if photos_count > 0:
            media_info += f"📸 Фото: {photos_count}\n"
        if videos_count > 0:
            media_info += f"🎥 Видео: {videos_count}\n"

        await message.reply_text(
            "🎉 <b>Заказ опубликован!</b>\n\n"
            f"📍 Город: {context.user_data['order_city']}\n"
            f"🔧 Категории: {categories_text}\n"
            f"{media_info}"
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

    # Получаем текущего пользователя для проверки, смотрит ли он свой профиль
    current_user = db.get_user(query.from_user.id)
    is_own_profile = False
    if current_user:
        current_user_dict = dict(current_user)
        is_own_profile = (current_user_dict['id'] == profile_user_id)

    # Получаем отзывы
    reviews = db.get_reviews_for_user(profile_user_id, role)

    if not reviews:
        # Определяем callback для кнопки "Назад"
        if is_own_profile:
            # Если смотрим свой профиль - возврат в меню
            back_callback = "show_worker_menu" if role == "worker" else "show_client_menu"
        else:
            # Если смотрим чужой профиль - возврат в профиль
            back_callback = "worker_profile" if role == "worker" else "show_client_menu"

        await query.edit_message_text(
            "📊 <b>Отзывы</b>\n\n"
            "Пока нет отзывов.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)
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

    # Определяем callback для кнопки "Назад"
    if is_own_profile:
        # Если смотрим свой профиль - возврат в меню
        back_callback = "show_worker_menu" if role == "worker" else "show_client_menu"
    else:
        # Если смотрим чужой профиль - возврат в профиль
        back_callback = "worker_profile" if role == "worker" else "show_client_menu"

    await query.edit_message_text(
        message_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)
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
