import os
from datetime import datetime

# Определяем тип базы данных
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Используем PostgreSQL
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import psycopg2.extras
    USE_POSTGRES = True
else:
    # Используем SQLite для локальной разработки
    import sqlite3
    DATABASE_NAME = "repair_platform.db"
    USE_POSTGRES = False


def get_connection():
    """Возвращает подключение к базе данных (PostgreSQL или SQLite)"""
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(DATABASE_NAME)
        conn.row_factory = sqlite3.Row
        return conn


def get_cursor(conn):
    """Возвращает курсор с правильными настройками"""
    if USE_POSTGRES:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
    else:
        cursor = conn.cursor()
    return DBCursor(cursor)


def convert_sql(sql):
    """Преобразует SQL из SQLite формата в PostgreSQL если нужно"""
    if USE_POSTGRES:
        # Заменяем placeholders
        sql = sql.replace('?', '%s')

        # Преобразуем типы данных
        sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
        sql = sql.replace('AUTOINCREMENT', '')  # Удаляем оставшиеся AUTOINCREMENT
        sql = sql.replace('TEXT', 'VARCHAR(1000)')
        sql = sql.replace('REAL', 'NUMERIC')
        sql = sql.replace('INTEGER', 'INTEGER')  # Оставляем как есть

        # Исправляем telegram_id - он должен быть BIGINT
        if 'telegram_id' in sql and 'INTEGER' in sql:
            sql = sql.replace('telegram_id INTEGER', 'telegram_id BIGINT')

    return sql


class DBCursor:
    """Обертка для cursor, автоматически преобразует SQL"""
    def __init__(self, cursor):
        self.cursor = cursor
        self._lastrowid = None

    def execute(self, sql, params=None):
        sql = convert_sql(sql)

        # Для PostgreSQL INSERT нужно добавить RETURNING id
        if USE_POSTGRES and sql.strip().upper().startswith('INSERT'):
            if 'RETURNING' not in sql.upper():
                sql = sql.rstrip().rstrip(';') + ' RETURNING id'

        if params:
            result = self.cursor.execute(sql, params)
        else:
            result = self.cursor.execute(sql)

        # Получаем lastrowid для PostgreSQL
        if USE_POSTGRES and sql.strip().upper().startswith('INSERT'):
            row = self.cursor.fetchone()
            if row:
                self._lastrowid = row['id'] if isinstance(row, dict) else row[0]

        return result

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def lastrowid(self):
        if USE_POSTGRES:
            return self._lastrowid
        return self.cursor.lastrowid


def init_db():
    with get_connection() as conn:
        cursor = get_cursor(conn)

        # Пользователи (convert_sql автоматически преобразует в PostgreSQL формат)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                role TEXT NOT NULL,
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
                photos TEXT DEFAULT '',
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
    # Для PostgreSQL миграции не нужны - таблицы создаются через init_db()
    if USE_POSTGRES:
        print("✅ Используется PostgreSQL, миграция не требуется")
        return

    with get_connection() as conn:
        cursor = get_cursor(conn)

        # Проверяем существует ли колонка (только для SQLite)
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
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()


def create_user(telegram_id, role):
    with get_connection() as conn:
        cursor = get_cursor(conn)
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
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
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
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO workers (user_id, name, phone, city, regions, categories, experience, description, portfolio_photos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, name, phone, city, regions, categories, experience, description, portfolio_photos))
        conn.commit()


def create_client_profile(user_id, name, phone, city, description):
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO clients (user_id, name, phone, city, description)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, phone, city, description))
        conn.commit()


def get_worker_profile(user_id):
    """Возвращает профиль мастера по user_id"""
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT w.*, u.telegram_id
            FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE w.user_id = ?
        """, (user_id,))
        return cursor.fetchone()


def get_client_profile(user_id):
    """Возвращает профиль заказчика по user_id"""
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT c.*, u.telegram_id
            FROM clients c
            JOIN users u ON c.user_id = u.id
            WHERE c.user_id = ?
        """, (user_id,))
        return cursor.fetchone()


def get_client_by_id(client_id):
    """Возвращает профиль заказчика по client_id"""
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM clients WHERE id = ?
        """, (client_id,))
        return cursor.fetchone()


def get_user_by_id(user_id):
    """Возвращает пользователя по user_id"""
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM users WHERE id = ?
        """, (user_id,))
        return cursor.fetchone()


# --- Рейтинг и отзывы ---

def update_user_rating(user_id, new_rating, role_to):
    with get_connection() as conn:
        cursor = get_cursor(conn)

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
    with get_connection() as conn:
        cursor = get_cursor(conn)
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
    
    with get_connection() as conn:
        cursor = get_cursor(conn)
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
    
    with get_connection() as conn:
        cursor = get_cursor(conn)
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
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        
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
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        
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
    # Для PostgreSQL миграции не нужны - таблицы создаются через init_db()
    if USE_POSTGRES:
        print("✅ Используется PostgreSQL, миграция не требуется")
        return

    with get_connection() as conn:
        cursor = get_cursor(conn)

        # Проверяем есть ли колонка photos (только для SQLite)
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
    # Для PostgreSQL миграции не нужны - таблицы создаются через init_db()
    if USE_POSTGRES:
        print("✅ Используется PostgreSQL, миграция не требуется")
        return

    with get_connection() as conn:
        cursor = get_cursor(conn)

        # Проверяем есть ли колонка currency (только для SQLite)
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
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
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
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        
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
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        
        cursor.execute("""
            SELECT * FROM orders
            WHERE client_id = ?
            ORDER BY created_at DESC
        """, (client_id,))
        
        return cursor.fetchall()


def get_order_by_id(order_id):
    """Получает заказ по ID"""
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        
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
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
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
    with get_connection() as conn:
        
        cursor = get_cursor(conn)
        
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
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        cursor.execute("""
            SELECT COUNT(*) FROM bids
            WHERE order_id = ? AND worker_id = ?
        """, (order_id, worker_id))
        
        return cursor.fetchone()[0] > 0


def select_bid(bid_id):
    """Отмечает отклик как выбранный"""
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
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

    with get_connection() as conn:
        cursor = get_cursor(conn)

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
            # Пользователь может быть мастером или клиентом - это не важно
            # Проверим наличие профиля клиента и создадим если нужно

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
            ("Сантехника", "Минск", "Установка смесителя на кухне", "fixed", 50),
            ("Отделка", "Минск", "Покраска стен в двух комнатах", "flexible", 200),
            ("Сборка мебели", "Минск", "Сборка шкафа-купе 2м", "fixed", 80),
            ("Окна/двери", "Минск", "Регулировка пластиковых окон", "none", 0),
            ("Бытовая техника", "Минск", "Ремонт стиральной машины", "flexible", 100),
            ("Напольные покрытия", "Минск", "Укладка ламината 20м²", "fixed", 300),
            ("Мелкий ремонт", "Минск", "Повесить полки и картины", "none", 0),
            ("Дизайн", "Минск", "Консультация по дизайну интерьера", "flexible", 150),
            ("Электрика", "Минск", "Установка люстры в зале", "fixed", 40),
            ("Сантехника", "Минск", "Замена унитаза", "flexible", 120),
            ("Отделка", "Минск", "Поклейка обоев в спальне", "fixed", 180),
            ("Сборка мебели", "Минск", "Сборка кухонного гарнитура", "flexible", 250),
            ("Окна/двери", "Минск", "Установка межкомнатной двери", "fixed", 100),
            ("Бытовая техника", "Минск", "Ремонт холодильника", "none", 0),
            ("Напольные покрытия", "Минск", "Укладка плитки в ванной 5м²", "fixed", 200),
            ("Мелкий ремонт", "Минск", "Замена замков на дверях", "flexible", 70),
            ("Электрика", "Минск", "Проводка света в гараже", "fixed", 150),
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


def add_test_workers(telegram_id):
    """
    Добавляет тестовых мастеров и их отклики на заказы.
    Используется только для пользователя с telegram_id = 641830790.

    Args:
        telegram_id: Telegram ID пользователя

    Returns:
        tuple: (success: bool, message: str, workers_created: int)
    """
    # Проверка, что это разрешенный пользователь
    if telegram_id != 641830790:
        return (False, "❌ Эта команда доступна только для администратора.", 0)

    with get_connection() as conn:
        cursor = get_cursor(conn)

        # Данные тестовых мастеров
        test_workers = [
            {
                "telegram_id": 100000001,
                "name": "Иван Петров",
                "phone": "+375291111111",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Электрика, Мелкий ремонт",
                "experience": "5-10 лет",
                "description": "Профессиональный электрик. Выполняю все виды электромонтажных работ. Качественно и в срок.",
                "rating": 4.8,
                "rating_count": 15
            },
            {
                "telegram_id": 100000002,
                "name": "Сергей Козлов",
                "phone": "+375292222222",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Сантехника, Отделка",
                "experience": "10+ лет",
                "description": "Опытный сантехник. Установка, ремонт, замена любого сантехнического оборудования.",
                "rating": 4.9,
                "rating_count": 23
            },
            {
                "telegram_id": 100000003,
                "name": "Александр Смирнов",
                "phone": "+375293333333",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Сборка мебели, Мелкий ремонт",
                "experience": "3-5 лет",
                "description": "Быстро и качественно соберу любую мебель. Работаю с инструкциями и без.",
                "rating": 4.7,
                "rating_count": 12
            },
            {
                "telegram_id": 100000004,
                "name": "Дмитрий Волков",
                "phone": "+375294444444",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Окна/двери, Напольные покрытия",
                "experience": "5-10 лет",
                "description": "Установка и ремонт окон, дверей. Укладка ламината, плитки. Гарантия качества.",
                "rating": 4.6,
                "rating_count": 18
            },
            {
                "telegram_id": 100000005,
                "name": "Андрей Новиков",
                "phone": "+375295555555",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Бытовая техника, Электрика",
                "experience": "10+ лет",
                "description": "Ремонт любой бытовой техники: холодильники, стиральные машины, СВЧ и др.",
                "rating": 4.9,
                "rating_count": 31
            },
            {
                "telegram_id": 100000006,
                "name": "Михаил Соколов",
                "phone": "+375296666666",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Отделка, Дизайн",
                "experience": "5-10 лет",
                "description": "Профессиональная отделка помещений. Консультации по дизайну интерьера.",
                "rating": 4.8,
                "rating_count": 20
            }
        ]

        workers_created = 0
        worker_ids = []

        # Создаем тестовых мастеров
        for worker_data in test_workers:
            try:
                # Проверяем, существует ли пользователь
                cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (worker_data["telegram_id"],))
                existing_user = cursor.fetchone()

                if not existing_user:
                    # Создаем пользователя
                    created_at = datetime.now().isoformat()
                    cursor.execute(
                        "INSERT INTO users (telegram_id, role, created_at) VALUES (?, ?, ?)",
                        (worker_data["telegram_id"], "worker", created_at)
                    )
                    user_id = cursor.lastrowid

                    # Создаем профиль мастера
                    cursor.execute("""
                        INSERT INTO workers (user_id, name, phone, city, regions, categories, experience, description, rating, rating_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id,
                        worker_data["name"],
                        worker_data["phone"],
                        worker_data["city"],
                        worker_data["regions"],
                        worker_data["categories"],
                        worker_data["experience"],
                        worker_data["description"],
                        worker_data["rating"],
                        worker_data["rating_count"]
                    ))
                    worker_id = cursor.lastrowid
                    worker_ids.append(worker_id)
                    workers_created += 1
                else:
                    # Получаем worker_id существующего мастера
                    user_id = existing_user[0] if isinstance(existing_user, tuple) else existing_user['id']
                    cursor.execute("SELECT id FROM workers WHERE user_id = ?", (user_id,))
                    worker_row = cursor.fetchone()
                    if worker_row:
                        worker_id = worker_row[0] if isinstance(worker_row, tuple) else worker_row['id']
                        worker_ids.append(worker_id)

            except Exception as e:
                print(f"Ошибка при создании мастера: {e}")

        # Получаем все открытые заказы
        cursor.execute("SELECT id, category FROM orders WHERE status = 'open'")
        orders = cursor.fetchall()

        # Создаем отклики от мастеров на подходящие заказы
        bids_created = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for order in orders:
            order_id = order[0] if isinstance(order, tuple) else order['id']
            order_category = order[1] if isinstance(order, tuple) else order['category']

            # Для каждого заказа добавляем 2-3 отклика от подходящих мастеров
            suitable_workers = []
            for i, worker_data in enumerate(test_workers):
                if i < len(worker_ids) and order_category in worker_data["categories"]:
                    suitable_workers.append((worker_ids[i], worker_data))

            # Добавляем отклики от первых 2-3 подходящих мастеров
            for worker_id, worker_data in suitable_workers[:3]:
                try:
                    # Проверяем, нет ли уже отклика
                    cursor.execute(
                        "SELECT COUNT(*) FROM bids WHERE order_id = ? AND worker_id = ?",
                        (order_id, worker_id)
                    )
                    existing_bid = cursor.fetchone()
                    bid_exists = existing_bid[0] if isinstance(existing_bid, tuple) else existing_bid['COUNT(*)']

                    if not bid_exists or bid_exists == 0:
                        # Генерируем цену (50-300 BYN)
                        import random
                        price = random.randint(50, 300)

                        # Создаем отклик
                        cursor.execute("""
                            INSERT INTO bids (order_id, worker_id, proposed_price, currency, comment, created_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            order_id,
                            worker_id,
                            price,
                            "BYN",
                            f"Готов выполнить работу качественно и в срок. Опыт {worker_data['experience']}.",
                            now,
                            "active"
                        ))
                        bids_created += 1

                except Exception as e:
                    print(f"Ошибка при создании отклика: {e}")

        conn.commit()

        message = f"✅ Успешно добавлено:\n• {workers_created} тестовых мастеров\n• {bids_created} откликов на заказы"
        return (True, message, workers_created)

