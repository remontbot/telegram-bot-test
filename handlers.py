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
        [InlineKeyboardButton("📸 Добавить фото работ", callback_data="worker_add_photos")],
        # сюда позже: "Доступные заказы", "Мои отклики"
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


# ------- ДОБАВЛЕНИЕ ФОТО ПОСЛЕ РЕГИСТРАЦИИ -------

async def worker_add_photos_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню для добавления фото работ после регистрации"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📸 <b>Добавление фото работ</b>\n\n"
        "Эта функция в разработке.\n\n"
        "Скоро вы сможете добавлять новые фотографии своих работ прямо из меню!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
        ])
    )


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
