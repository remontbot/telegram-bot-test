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
