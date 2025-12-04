import sqlite3
from datetime import datetime

DATABASE_NAME = "repair_platform.db"


def init_db():
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()

        # Пользователи
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                role TEXT NOT NULL, -- 'worker' или 'client'
                created_at TEXT NOT NULL
            );
        """)

        # Мастера
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                name TEXT,
                phone TEXT,
                city TEXT,
                regions TEXT,
                categories TEXT,
                experience TEXT,
                description TEXT,
                portfolio_photos TEXT,
                rating REAL DEFAULT 0.0,
                rating_count INTEGER DEFAULT 0,
                verified_reviews INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        # Заказчики
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                name TEXT,
                phone TEXT,
                city TEXT,
                description TEXT,
                rating REAL DEFAULT 0.0,
                rating_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        # Заказы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                title TEXT,
                description TEXT,
                city TEXT,
                address TEXT,
                category TEXT,
                budget_type TEXT, -- 'fixed' или 'flexible'
                budget_value REAL,
                deadline TEXT,
                status TEXT NOT NULL, -- 'open', 'pending_choice', 'master_selected', 'contact_shared', 'done', 'canceled'
                created_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES clients(id)
            );
        """)

        # Отклики мастеров
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                proposed_price REAL,
                currency TEXT DEFAULT 'BYN',
                proposed_deadline TEXT,
                comment TEXT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL, -- 'active', 'rejected', 'selected', 'expired'
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (worker_id) REFERENCES workers(id)
            );
        """)

        # Оплата за доступ к контактам
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                paid INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (worker_id) REFERENCES workers(id),
                FOREIGN KEY (client_id) REFERENCES clients(id)
            );
        """)

        # Отзывы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                role_from TEXT NOT NULL,
                role_to TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (order_id, from_user_id, to_user_id),
                FOREIGN KEY (from_user_id) REFERENCES users(id),
                FOREIGN KEY (to_user_id) REFERENCES users(id),
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );
        """)

        conn.commit()


def migrate_add_portfolio_photos():
    """Миграция: добавляет колонку portfolio_photos если её нет"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        
        # Проверяем существует ли колонка
        cursor.execute("PRAGMA table_info(workers)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'portfolio_photos' not in columns:
            print("⚠️  Колонка 'portfolio_photos' отсутствует, добавляю...")
            cursor.execute("""
                ALTER TABLE workers 
                ADD COLUMN portfolio_photos TEXT DEFAULT ''
            """)
            conn.commit()
            print("✅ Колонка 'portfolio_photos' успешно добавлена!")
        else:
            print("✅ Колонка 'portfolio_photos' уже существует")


# --- Пользователи ---

def get_user(telegram_id):
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()


def create_user(telegram_id, role):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        created_at = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO users (telegram_id, role, created_at) VALUES (?, ?, ?)",
            (telegram_id, role, created_at),
        )
        conn.commit()
        return cursor.lastrowid


def delete_user_profile(telegram_id):
    """
    Полностью удаляет профиль пользователя из базы данных.
    Возвращает True, если удаление прошло успешно, False если пользователь не найден.
    """
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        
        # Сначала получаем user_id
        cursor.execute("SELECT id, role FROM users WHERE telegram_id = ?", (telegram_id,))
        user_row = cursor.fetchone()
        
        if not user_row:
            return False
        
        user_id, role = user_row
        
        # Удаляем из таблицы профиля (workers или clients)
        if role == "worker":
            cursor.execute("DELETE FROM workers WHERE user_id = ?", (user_id,))
        elif role == "client":
            cursor.execute("DELETE FROM clients WHERE user_id = ?", (user_id,))
        
        # Удаляем пользователя из таблицы users
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        
        conn.commit()
        return True


# --- Профили мастеров и заказчиков ---

def create_worker_profile(user_id, name, phone, city, regions, categories, experience, description, portfolio_photos=""):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO workers (user_id, name, phone, city, regions, categories, experience, description, portfolio_photos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, name, phone, city, regions, categories, experience, description, portfolio_photos))
        conn.commit()


def create_client_profile(user_id, name, phone, city, description):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO clients (user_id, name, phone, city, description)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, phone, city, description))
        conn.commit()


def get_worker_profile(user_id):
    """Возвращает профиль мастера по user_id"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT w.*, u.telegram_id
            FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE w.user_id = ?
        """, (user_id,))
        return cursor.fetchone()


def get_client_profile(user_id):
    """Возвращает профиль заказчика по user_id"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, u.telegram_id
            FROM clients c
            JOIN users u ON c.user_id = u.id
            WHERE c.user_id = ?
        """, (user_id,))
        return cursor.fetchone()


def get_client_by_id(client_id):
    """Возвращает профиль заказчика по client_id"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM clients WHERE id = ?
        """, (client_id,))
        return cursor.fetchone()


def get_user_by_id(user_id):
    """Возвращает пользователя по user_id"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM users WHERE id = ?
        """, (user_id,))
        return cursor.fetchone()


# --- Рейтинг и отзывы ---

def update_user_rating(user_id, new_rating, role_to):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()

        if role_to == "worker":
            cursor.execute("SELECT rating, rating_count FROM workers WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            current_rating = row[0] if row else 0.0
            rating_count = row[1] if row else 0

            new_total = current_rating * rating_count + new_rating
            new_count = rating_count + 1
            avg = new_total / new_count if new_count > 0 else 0.0

            cursor.execute(
                "UPDATE workers SET rating = ?, rating_count = ? WHERE user_id = ?",
                (avg, new_count, user_id),
            )

        elif role_to == "client":
            cursor.execute("SELECT rating, rating_count FROM clients WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            current_rating = row[0] if row else 0.0
            rating_count = row[1] if row else 0

            new_total = current_rating * rating_count + new_rating
            new_count = rating_count + 1
            avg = new_total / new_count if new_count > 0 else 0.0

            cursor.execute(
                "UPDATE clients SET rating = ?, rating_count = ? WHERE user_id = ?",
                (avg, new_count, user_id),
            )

        conn.commit()


def add_review(from_user_id, to_user_id, order_id, role_from, role_to, rating, comment):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        created_at = datetime.now().isoformat()
        try:
            cursor.execute("""
                INSERT INTO reviews
                (from_user_id, to_user_id, order_id, role_from, role_to, rating, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (from_user_id, to_user_id, order_id, role_from, role_to, rating, comment, created_at))
            conn.commit()
            update_user_rating(to_user_id, rating, role_to)
            return True
        except sqlite3.IntegrityError:
            return False


# --- Обновление полей профиля мастера ---

def update_worker_field(user_id, field_name, new_value):
    """
    Универсальная функция для обновления любого поля профиля мастера.
    Используется для редактирования профиля без потери рейтинга и истории.
    
    Args:
        user_id: ID пользователя
        field_name: Название поля (name, phone, city, etc.)
        new_value: Новое значение
    """
    allowed_fields = ["name", "phone", "city", "regions", "categories", 
                      "experience", "description", "portfolio_photos"]
    
    if field_name not in allowed_fields:
        raise ValueError(f"Недопустимое поле: {field_name}")
    
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        query = f"UPDATE workers SET {field_name} = ? WHERE user_id = ?"
        cursor.execute(query, (new_value, user_id))
        conn.commit()
        
        return cursor.rowcount > 0


def update_client_field(user_id, field_name, new_value):
    """
    Универсальная функция для обновления любого поля профиля заказчика.
    
    Args:
        user_id: ID пользователя
        field_name: Название поля (name, phone, city, description)
        new_value: Новое значение
    """
    allowed_fields = ["name", "phone", "city", "description"]
    
    if field_name not in allowed_fields:
        raise ValueError(f"Недопустимое поле: {field_name}")
    
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        query = f"UPDATE clients SET {field_name} = ? WHERE user_id = ?"
        cursor.execute(query, (new_value, user_id))
        conn.commit()
        
        return cursor.rowcount > 0


# --- Поиск мастеров ---

def get_all_workers(city=None, category=None):
    """
    Получает список всех мастеров с фильтрами.
    
    Args:
        city: Фильтр по городу (опционально)
        category: Фильтр по категории (опционально)
    
    Returns:
        List of worker profiles with user info
    """
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = """
            SELECT 
                w.*,
                u.telegram_id
            FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE 1=1
        """
        params = []
        
        if city:
            query += " AND w.city LIKE ?"
            params.append(f"%{city}%")
        
        if category:
            query += " AND w.categories LIKE ?"
            params.append(f"%{category}%")
        
        query += " ORDER BY w.rating DESC, w.rating_count DESC"
        
        cursor.execute(query, params)
        return cursor.fetchall()


def get_worker_by_id(worker_id):
    """Получает профиль мастера по ID"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                w.*,
                u.telegram_id
            FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE w.id = ?
        """, (worker_id,))
        
        return cursor.fetchone()



def migrate_add_order_photos():
    """Добавляет колонку photos в таблицу orders"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        
        # Проверяем есть ли колонка photos
        cursor.execute("PRAGMA table_info(orders)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'photos' not in columns:
            print("➕ Добавляем колонку 'photos' в таблицу orders...")
            cursor.execute("ALTER TABLE orders ADD COLUMN photos TEXT DEFAULT ''")
            conn.commit()
            print("✅ Колонка 'photos' успешно добавлена в orders!")
        else:
            print("✅ Колонка 'photos' уже существует в orders")


def migrate_add_currency_to_bids():
    """Добавляет колонку currency в таблицу bids"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        
        # Проверяем есть ли колонка currency
        cursor.execute("PRAGMA table_info(bids)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'currency' not in columns:
            print("➕ Добавляем колонку 'currency' в таблицу bids...")
            cursor.execute("ALTER TABLE bids ADD COLUMN currency TEXT DEFAULT 'BYN'")
            conn.commit()
            print("✅ Колонка 'currency' успешно добавлена в bids!")
        else:
            print("✅ Колонка 'currency' уже существует в bids")

def create_order(client_id, city, categories, description, photos, budget_type="none", budget_value=0):
    """Создаёт новый заказ"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Преобразуем список категорий в строку
        categories_str = ", ".join(categories) if isinstance(categories, list) else categories
        
        # Преобразуем список фото в строку
        photos_str = ",".join(photos) if isinstance(photos, list) else photos
        
        cursor.execute("""
            INSERT INTO orders (
                client_id, city, category, description, photos,
                budget_type, budget_value, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """, (client_id, city, categories_str, description, photos_str, budget_type, budget_value, now))
        
        conn.commit()
        return cursor.lastrowid


def get_orders_by_category(category):
    """Получает открытые заказы по категории"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                o.*,
                c.name as client_name,
                c.rating as client_rating,
                c.rating_count as client_rating_count
            FROM orders o
            JOIN clients c ON o.client_id = c.id
            WHERE o.status = 'open'
            AND o.category LIKE ?
            ORDER BY o.created_at DESC
        """, (f"%{category}%",))
        
        return cursor.fetchall()


def get_client_orders(client_id):
    """Получает все заказы клиента"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM orders
            WHERE client_id = ?
            ORDER BY created_at DESC
        """, (client_id,))
        
        return cursor.fetchall()


def get_order_by_id(order_id):
    """Получает заказ по ID"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                o.*,
                c.name as client_name,
                c.phone as client_phone,
                c.rating as client_rating,
                c.rating_count as client_rating_count
            FROM orders o
            JOIN clients c ON o.client_id = c.id
            WHERE o.id = ?
        """, (order_id,))
        
        return cursor.fetchone()


def create_bid(order_id, worker_id, proposed_price, currency, comment=""):
    """Создаёт отклик мастера на заказ"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT INTO bids (
                order_id, worker_id, proposed_price, currency, 
                comment, created_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """, (order_id, worker_id, proposed_price, currency, comment, now))
        
        conn.commit()
        return cursor.lastrowid


def get_bids_for_order(order_id):
    """Получает все отклики для заказа"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                b.*,
                w.name as worker_name,
                w.rating as worker_rating,
                w.rating_count as worker_rating_count,
                w.experience as worker_experience,
                w.phone as worker_phone
            FROM bids b
            JOIN workers w ON b.worker_id = w.id
            WHERE b.order_id = ?
            AND b.status = 'active'
            ORDER BY b.created_at ASC
        """, (order_id,))
        
        return cursor.fetchall()


def check_worker_bid_exists(order_id, worker_id):
    """Проверяет, откликался ли уже мастер на этот заказ"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM bids
            WHERE order_id = ? AND worker_id = ?
        """, (order_id, worker_id))
        
        return cursor.fetchone()[0] > 0


def select_bid(bid_id):
    """Отмечает отклик как выбранный"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        
        # Получаем order_id из отклика
        cursor.execute("SELECT order_id FROM bids WHERE id = ?", (bid_id,))
        result = cursor.fetchone()
        if not result:
            return False
        
        order_id = result[0]
        
        # Обновляем статус выбранного отклика
        cursor.execute("""
            UPDATE bids 
            SET status = 'selected'
            WHERE id = ?
        """, (bid_id,))
        
        # Остальные отклики отмечаем как rejected
        cursor.execute("""
            UPDATE bids 
            SET status = 'rejected'
            WHERE order_id = ? AND id != ?
        """, (order_id, bid_id))
        
        # Обновляем статус заказа
        cursor.execute("""
            UPDATE orders
            SET status = 'master_selected'
            WHERE id = ?
        """, (order_id,))

        conn.commit()
        return True


def add_test_orders(telegram_id):
    """
    Добавляет 18 тестовых заказов для указанного пользователя.
    Используется только для пользователя с telegram_id = 641830790.

    Args:
        telegram_id: Telegram ID пользователя

    Returns:
        tuple: (success: bool, message: str, orders_created: int)
    """
    # Проверка, что это разрешенный пользователь
    if telegram_id != 641830790:
        return (False, "❌ Эта команда доступна только для администратора.", 0)

    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()

        # Получаем или создаем пользователя
        cursor.execute("SELECT id, role FROM users WHERE telegram_id = ?", (telegram_id,))
        user_row = cursor.fetchone()

        if not user_row:
            # Создаем пользователя как клиента
            created_at = datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO users (telegram_id, role, created_at) VALUES (?, ?, ?)",
                (telegram_id, "client", created_at)
            )
            user_id = cursor.lastrowid

            # Создаем профиль клиента
            cursor.execute("""
                INSERT INTO clients (user_id, name, phone, city, description)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, "Тестовый клиент", "+375291234567", "Минск", "Тестовый профиль"))
        else:
            user_id = user_row[0]
            role = user_row[1]

            # Если пользователь не клиент, проверяем профиль клиента
            if role != "client":
                return (False, "❌ Пользователь не является клиентом.", 0)

        # Получаем client_id
        cursor.execute("SELECT id FROM clients WHERE user_id = ?", (user_id,))
        client_row = cursor.fetchone()

        if not client_row:
            # Создаем профиль клиента, если его нет
            cursor.execute("""
                INSERT INTO clients (user_id, name, phone, city, description)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, "Тестовый клиент", "+375291234567", "Минск", "Тестовый профиль"))
            client_id = cursor.lastrowid
        else:
            client_id = client_row[0]

        # Данные для создания тестовых заказов
        categories = [
            "Электрика", "Сантехника", "Отделка", "Сборка мебели",
            "Окна/двери", "Бытовая техника", "Напольные покрытия",
            "Мелкий ремонт", "Дизайн"
        ]

        cities = ["Минск", "Гомель", "Могилёв", "Витебск", "Гродно", "Брест"]

        test_orders = [
            ("Электрика", "Минск", "Замена розеток в квартире", "none", 0),
            ("Сантехника", "Гомель", "Установка смесителя на кухне", "fixed", 50),
            ("Отделка", "Могилёв", "Покраска стен в двух комнатах", "flexible", 200),
            ("Сборка мебели", "Витебск", "Сборка шкафа-купе 2м", "fixed", 80),
            ("Окна/двери", "Гродно", "Регулировка пластиковых окон", "none", 0),
            ("Бытовая техника", "Брест", "Ремонт стиральной машины", "flexible", 100),
            ("Напольные покрытия", "Минск", "Укладка ламината 20м²", "fixed", 300),
            ("Мелкий ремонт", "Гомель", "Повесить полки и картины", "none", 0),
            ("Дизайн", "Могилёв", "Консультация по дизайну интерьера", "flexible", 150),
            ("Электрика", "Витебск", "Установка люстры в зале", "fixed", 40),
            ("Сантехника", "Гродно", "Замена унитаза", "flexible", 120),
            ("Отделка", "Брест", "Поклейка обоев в спальне", "fixed", 180),
            ("Сборка мебели", "Минск", "Сборка кухонного гарнитура", "flexible", 250),
            ("Окна/двери", "Гомель", "Установка межкомнатной двери", "fixed", 100),
            ("Бытовая техника", "Могилёв", "Ремонт холодильника", "none", 0),
            ("Напольные покрытия", "Витебск", "Укладка плитки в ванной 5м²", "fixed", 200),
            ("Мелкий ремонт", "Гродно", "Замена замков на дверях", "flexible", 70),
            ("Электрика", "Брест", "Проводка света в гараже", "fixed", 150),
        ]

        # Создаем заказы
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        orders_created = 0

        for category, city, description, budget_type, budget_value in test_orders:
            try:
                cursor.execute("""
                    INSERT INTO orders (
                        client_id, city, category, description, photos,
                        budget_type, budget_value, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """, (client_id, city, category, description, "", budget_type, budget_value, now))
                orders_created += 1
            except Exception as e:
                print(f"Ошибка при создании заказа: {e}")

        conn.commit()

        return (True, f"✅ Успешно добавлено {orders_created} тестовых заказов!", orders_created)

