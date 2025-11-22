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
    REGISTER_MASTER_REGIONS,
    REGISTER_MASTER_CATEGORIES_SELECT,
    REGISTER_MASTER_CATEGORIES_OTHER,
    REGISTER_MASTER_EXPERIENCE,
    REGISTER_MASTER_DESCRIPTION,
    REGISTER_CLIENT_NAME,
    REGISTER_CLIENT_PHONE,
    REGISTER_CLIENT_CITY,
    REGISTER_CLIENT_DESCRIPTION,
) = range(13)


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
        role = user["role"]
        if role == "worker":
            keyboard = [[InlineKeyboardButton("Моё меню мастера", callback_data="show_worker_menu")]]
            await update.message.reply_text(
                "Вы уже зарегистрированы как мастер.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        elif role == "client":
            keyboard = [[InlineKeyboardButton("Моё меню заказчика", callback_data="show_client_menu")]]
            await update.message.reply_text(
                "Вы уже зарегистрированы как заказчик.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        return ConversationHandler.END

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
    context.user_data["city"] = update.message.text.strip()
    await update.message.reply_text(
        "📍 В каких районах/территориях вы работаете?\n"
        "Введите через запятую.\n\n"
        "Например: «Фрунзенский, Центральный» или «Все районы Минска»."
    )
    return REGISTER_MASTER_REGIONS


async def register_master_regions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["regions"] = update.message.text.strip()

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
        "🔧 Какие виды работ вы выполняете?\n\n"
        "Нажимайте подходящие кнопки (можно несколько).\n"
        "Если нужного варианта нет — выберите «Другое» и впишите свои.\n"
        "Когда закончите — нажмите «✅ Завершить выбор».",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return REGISTER_MASTER_CATEGORIES_SELECT


async def register_master_categories_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    selected = data.split("_", 1)[1]

    if selected == "done":
        if not context.user_data["categories"]:
            await query.edit_message_text(
                "Нужно выбрать хотя бы один вид работ или указать «Другое»."
            )
            return REGISTER_MASTER_CATEGORIES_SELECT

        text = (
            "Выбранные категории: "
            + ", ".join(context.user_data["categories"])
            + "\n\nТеперь укажем ваш опыт работы.\n"
              "Напишите, например: «Начинающий», «1–3 года», «3–5 лет», «Более 5 лет»."
        )
        await query.edit_message_text(text)
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
            await query.answer(f"{selected} уже выбрана")

        return REGISTER_MASTER_CATEGORIES_SELECT


async def register_master_categories_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_cats = update.message.text.strip()
    custom_list = [c.strip() for c in user_cats.split(",") if c.strip()]
    context.user_data["categories"].extend(custom_list)

    await update.message.reply_text(
        "Отлично 👍\n\n"
        "Теперь укажите ваш опыт работы.\n"
        "Пример: «Начинающий», «1–3 года», «3–5 лет», «Более 5 лет»."
    )
    return REGISTER_MASTER_EXPERIENCE


async def register_master_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["experience"] = update.message.text.strip()
    await update.message.reply_text(
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

    telegram_id = update.effective_user.id
    user_id = db.create_user(telegram_id, "worker")

    db.create_worker_profile(
        user_id=user_id,
        name=context.user_data["name"],
        phone=context.user_data["phone"],
        city=context.user_data["city"],
        regions=context.user_data["regions"],
        categories=",".join(context.user_data["categories"]),
        experience=context.user_data["experience"],
        description=context.user_data["description"],
    )

    keyboard = [[InlineKeyboardButton("Моё меню мастера", callback_data="show_worker_menu")]]
    await update.message.reply_text(
        "🥳 Профиль мастера создан!\n\n"
        "Теперь вы можете открыть меню мастера, посмотреть свой профиль и в будущем получать заказы.",
        reply_markup=InlineKeyboardMarkup(keyboard),
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
    await update.message.reply_text(
        "Кратко о себе (можете пропустить, отправив «-»).\n"
        "Например: «Ищу мастера для ремонта квартиры, важно аккуратно и по договору»."
    )
    return REGISTER_CLIENT_DESCRIPTION


async def register_client_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    context.user_data["description"] = desc if desc != "-" else ""

    telegram_id = update.effective_user.id
    user_id = db.create_user(telegram_id, "client")

    db.create_client_profile(
        user_id=user_id,
        name=context.user_data["name"],
        phone=context.user_data["phone"],
        city=context.user_data["city"],
        description=context.user_data["description"],
    )

    keyboard = [[InlineKeyboardButton("Моё меню заказчика", callback_data="show_client_menu")]]
    await update.message.reply_text(
        "🥳 Профиль заказчика создан!\n\n"
        "Теперь вы можете создавать заказы и выбирать мастеров.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    context.user_data.clear()
    return ConversationHandler.END


# ------- МЕНЮ -------

async def show_worker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👤 Мой профиль", callback_data="worker_profile")],
        # сюда позже можно добавить: "Доступные заказы", "Мои отклики"
    ]
    await query.edit_message_text(
        "🧰 Меню мастера.\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📝 Создать заказ", callback_data="client_create_order")],
        [InlineKeyboardButton("📂 Мои заказы", callback_data="client_my_orders")],
    ]
    await query.edit_message_text(
        "🏠 Меню заказчика.\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ------- ПРОФИЛЬ МАСТЕРА -------

async def show_worker_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)

    # 1) Проверяем, что вообще есть пользователь и он мастер
    if not user or user["role"] != "worker":
        await query.edit_message_text(
            "Профиль мастера не найден. Попробуйте пройти регистрацию заново через /start."
        )
        return

    # 2) user_id корректно берём из строки users.id
    user_id = user["id"]

    # 3) Берём профиль мастера по user_id
    worker_profile = db.get_worker_profile(user_id)

    if not worker_profile:
        await query.edit_message_text(
            "Похоже, ваш профиль мастера ещё не заполнен.\n\n"
            "Если вы только что регистрировались, попробуйте использовать команду /reset_profile для очистки и повторной регистрации."
        )
        return

    name = worker_profile.get("name", "—") or "—"
    phone = worker_profile.get("phone", "—") or "—"
    city = worker_profile.get("city", "—") or "—"
    regions = worker_profile.get("regions", "—") or "—"
    categories = worker_profile.get("categories", "—") or "—"
    experience = worker_profile.get("experience", "—") or "—"
    description = worker_profile.get("description", "—") or "—"
    rating = worker_profile.get("rating", 0)
    rating_count = worker_profile.get("rating_count", 0)
    
    if rating and rating > 0:
        rating_text = f"⭐ {rating:.1f} ({rating_count} отзывов)"
    else:
        rating_text = "Нет отзывов"

    text = (
        "👤 <b>Ваш профиль мастера</b>\n\n"
        f"<b>Имя:</b> {name}\n"
        f"<b>Телефон:</b> {phone}\n"
        f"<b>Город:</b> {city}\n"
        f"<b>Районы:</b> {regions}\n"
        f"<b>Виды работ:</b> {categories}\n"
        f"<b>Опыт:</b> {experience}\n"
        f"<b>Описание:</b> {description}\n"
        f"<b>Рейтинг:</b> {rating_text}\n"
    )

    keyboard = [
        [InlineKeyboardButton("⬅️ Назад в меню мастера", callback_data="show_worker_menu")],
    ]

    await query.edit_message_text(
        text=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
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


# ------- НОВАЯ ФУНКЦИЯ: ОЧИСТКА ПРОФИЛЯ -------

async def reset_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для полной очистки профиля пользователя из базы данных"""
    telegram_id = update.effective_user.id
    
    # Удаляем профиль из базы
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
