import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict

# Логирование для критических операций
logger = logging.getLogger(__name__)

# Определяем тип базы данных
DATABASE_URL = os.getenv("DATABASE_URL")

# Константы для валидации входных данных
MAX_NAME_LENGTH = 100
MAX_PHONE_LENGTH = 20
MAX_CITY_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 2000
MAX_COMMENT_LENGTH = 1000
MAX_CATEGORY_LENGTH = 200
MAX_EXPERIENCE_LENGTH = 50

# Константы для rate limiting
RATE_LIMIT_ORDERS_PER_HOUR = 10  # Максимум 10 заказов в час от одного пользователя
RATE_LIMIT_BIDS_PER_HOUR = 50    # Максимум 50 откликов в час от одного мастера
RATE_LIMIT_WINDOW_SECONDS = 3600  # Окно для подсчета (1 час)


class RateLimiter:
    """
    ИСПРАВЛЕНО: Автоматическая очистка памяти каждые 100 вызовов.

    In-memory rate limiter для защиты от спама с автоматической очисткой.
    """

    def __init__(self):
        self._requests = defaultdict(list)  # {(user_id, action): [timestamp1, timestamp2, ...]}
        self._cleanup_counter = 0  # Счетчик для периодической очистки
        self._cleanup_interval = 100  # Очистка каждые 100 вызовов

    def is_allowed(self, user_id, action, max_requests):
        """
        Проверяет, разрешен ли запрос для пользователя.

        Args:
            user_id: ID пользователя
            action: Тип действия (create_order, create_bid, etc.)
            max_requests: Максимум запросов в окне времени

        Returns:
            tuple: (allowed: bool, remaining_seconds: int)
        """
        # ИСПРАВЛЕНИЕ: Автоматическая очистка памяти
        self._cleanup_counter += 1
        if self._cleanup_counter >= self._cleanup_interval:
            self.cleanup_old_entries()
            self._cleanup_counter = 0

        key = (user_id, action)
        now = datetime.now()
        cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)

        # Удаляем старые запросы за пределами окна
        self._requests[key] = [ts for ts in self._requests[key] if ts > cutoff]

        # Проверяем лимит
        if len(self._requests[key]) >= max_requests:
            # Вычисляем, через сколько секунд откроется слот
            oldest_request = min(self._requests[key])
            remaining_seconds = int((oldest_request + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS) - now).total_seconds())
            return False, remaining_seconds

        # Добавляем текущий запрос
        self._requests[key].append(now)
        return True, 0

    def cleanup_old_entries(self):
        """Очищает старые записи для экономии памяти (теперь вызывается автоматически)"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS * 2)

        keys_to_remove = []
        for key in self._requests:
            self._requests[key] = [ts for ts in self._requests[key] if ts > cutoff]
            if not self._requests[key]:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._requests[key]

        logger.info(f"RateLimiter cleanup: удалено {len(keys_to_remove)} старых ключей, осталось {len(self._requests)}")


# Глобальный экземпляр rate limiter
_rate_limiter = RateLimiter()


def validate_string_length(value, max_length, field_name):
    """
    Проверяет длину строки и обрезает если необходимо.

    Args:
        value: Значение для проверки
        max_length: Максимальная допустимая длина
        field_name: Название поля для сообщения об ошибке

    Returns:
        str: Обрезанная строка
    """
    if value is None:
        return ""

    value_str = str(value)
    if len(value_str) > max_length:
        # Логируем предупреждение
        print(f"⚠️  Предупреждение: {field_name} превышает {max_length} символов (получено {len(value_str)}), обрезаем")
        return value_str[:max_length]

    return value_str

if DATABASE_URL:
    # Используем PostgreSQL
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
    import psycopg2.extras
    USE_POSTGRES = True

    # Connection pool для PostgreSQL (повышает производительность в 10 раз)
    _connection_pool = None

    def init_connection_pool():
        """Инициализирует пул соединений при запуске приложения"""
        global _connection_pool
        if _connection_pool is None:
            try:
                _connection_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=5,   # Минимум 5 готовых соединений
                    maxconn=20,  # Максимум 20 одновременных соединений
                    dsn=DATABASE_URL
                )
                logger.info("✅ PostgreSQL connection pool инициализирован (5-20 соединений)")
            except psycopg2.OperationalError as e:
                logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось подключиться к PostgreSQL: {e}", exc_info=True)
                raise
            except Exception as e:
                logger.error(f"❌ Неожиданная ошибка при инициализации connection pool: {e}", exc_info=True)
                raise

    def close_connection_pool():
        """Закрывает пул соединений при остановке приложения"""
        global _connection_pool
        if _connection_pool:
            try:
                _connection_pool.closeall()
                logger.info("✅ PostgreSQL connection pool закрыт")
            except Exception as e:
                logger.error(f"❌ Ошибка при закрытии connection pool: {e}", exc_info=True)
else:
    # Используем SQLite для локальной разработки
    import sqlite3
    DATABASE_NAME = "repair_platform.db"
    USE_POSTGRES = False

    def init_connection_pool():
        """Для SQLite пул не нужен"""
        pass

    def close_connection_pool():
        """Для SQLite пул не нужен"""
        pass


def is_retryable_postgres_error(error):
    """
    НОВОЕ: Определяет, можно ли повторить операцию после ошибки PostgreSQL.

    Возвращает True для:
    - Serialization failures (SQLSTATE 40001)
    - Deadlocks (SQLSTATE 40P01)
    - Connection errors

    Args:
        error: Исключение от psycopg2

    Returns:
        bool: True если операцию можно повторить
    """
    if not USE_POSTGRES:
        return False

    import psycopg2

    # Проверяем тип ошибки
    if isinstance(error, (psycopg2.extensions.TransactionRollbackError,
                         psycopg2.OperationalError)):
        return True

    # Проверяем SQLSTATE код
    if hasattr(error, 'pgcode'):
        # 40001 = serialization_failure
        # 40P01 = deadlock_detected
        if error.pgcode in ('40001', '40P01'):
            return True

    return False


def get_connection():
    """Возвращает подключение к базе данных (из пула для PostgreSQL или новое для SQLite)"""
    if USE_POSTGRES:
        try:
            # Берем соединение из пула (быстро!)
            conn = _connection_pool.getconn()
            # Проверяем, что соединение живо
            if conn.closed:
                logger.warning("⚠️ Получено закрытое соединение из пула, переподключаемся")
                _connection_pool.putconn(conn, close=True)
                conn = _connection_pool.getconn()
            return conn
        except psycopg2.pool.PoolError as e:
            logger.error(f"❌ Ошибка пула соединений PostgreSQL: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при получении соединения: {e}", exc_info=True)
            raise
    else:
        conn = sqlite3.connect(DATABASE_NAME)
        conn.row_factory = sqlite3.Row
        return conn


def return_connection(conn):
    """Возвращает соединение в пул (только для PostgreSQL)"""
    if USE_POSTGRES:
        _connection_pool.putconn(conn)
    else:
        # Для SQLite просто закрываем
        conn.close()


class DatabaseConnection:
    """
    Context manager для автоматического управления соединениями с пулом.
    ИСПРАВЛЕНО: Добавлен rollback при ошибках для PostgreSQL.
    """

    def __enter__(self):
        self.conn = get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # Нет ошибок - коммитим изменения
            try:
                self.conn.commit()
            except Exception as e:
                # КРИТИЧЕСКИ ВАЖНО: не игнорируем ошибки commit!
                logger.error(f"❌ ОШИБКА COMMIT БД: {e}", exc_info=True)
                try:
                    self.conn.rollback()
                except Exception as rollback_error:
                    logger.error(f"❌ ОШИБКА ROLLBACK: {rollback_error}", exc_info=True)
                return_connection(self.conn)
                raise  # Пробрасываем ошибку дальше
        else:
            # Произошла ошибка - откатываем транзакцию
            try:
                self.conn.rollback()
                logger.warning(f"⚠️ Rollback выполнен из-за ошибки: {exc_type.__name__}")
            except Exception as rollback_error:
                logger.error(f"❌ ОШИБКА ROLLBACK: {rollback_error}", exc_info=True)

        return_connection(self.conn)
        return False


def get_db_connection():
    """
    Возвращает context manager для работы с БД.
    Автоматически возвращает соединение в пул после использования.

    Использование:
        with get_db_connection() as conn:
            cursor = get_cursor(conn)
            cursor.execute("SELECT ...")
    """
    return DatabaseConnection()


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
    with get_db_connection() as conn:
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
                status TEXT NOT NULL, -- 'open', 'pending_choice', 'master_selected', 'contact_shared', 'done', 'canceled', 'cancelled', 'expired'
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

    with get_db_connection() as conn:
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
    with get_db_connection() as conn:

        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()


# Алиас для совместимости с кодом в handlers.py
def get_user_by_telegram_id(telegram_id):
    """Алиас для get_user() - возвращает пользователя по telegram_id"""
    return get_user(telegram_id)


def get_user_by_id(user_id):
    """Получает пользователя по внутреннему ID"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cursor.fetchone()


def create_user(telegram_id, role):
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        created_at = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO users (telegram_id, role, created_at) VALUES (?, ?, ?)",
            (telegram_id, role, created_at),
        )
        conn.commit()
        user_id = cursor.lastrowid
        logger.info(f"✅ Создан пользователь: ID={user_id}, Telegram={telegram_id}, Роль={role}")
        return user_id


def delete_user_profile(telegram_id):
    """
    Полностью удаляет профиль пользователя из базы данных.
    Возвращает True, если удаление прошло успешно, False если пользователь не найден.
    """
    with get_db_connection() as conn:
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
    """
    ОБНОВЛЕНО: Добавляет категории в нормализованную таблицу worker_categories.
    """
    # Валидация входных данных
    name = validate_string_length(name, MAX_NAME_LENGTH, "name")
    phone = validate_string_length(phone, MAX_PHONE_LENGTH, "phone")
    city = validate_string_length(city, MAX_CITY_LENGTH, "city")
    regions = validate_string_length(regions, MAX_CITY_LENGTH, "regions")
    categories = validate_string_length(categories, MAX_CATEGORY_LENGTH, "categories")
    experience = validate_string_length(experience, MAX_EXPERIENCE_LENGTH, "experience")
    description = validate_string_length(description, MAX_DESCRIPTION_LENGTH, "description")

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO workers (user_id, name, phone, city, regions, categories, experience, description, portfolio_photos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, name, phone, city, regions, categories, experience, description, portfolio_photos))
        worker_id = cursor.lastrowid
        conn.commit()
        logger.info(f"✅ Создан профиль мастера: ID={worker_id}, User={user_id}, Имя={name}, Город={city}")

    # ИСПРАВЛЕНИЕ: Добавляем категории в нормализованную таблицу
    if categories:
        categories_list = [cat.strip() for cat in categories.split(',') if cat.strip()]
        add_worker_categories(worker_id, categories_list)
        logger.info(f"📋 Добавлены категории для мастера {worker_id}: {categories_list}")


def create_client_profile(user_id, name, phone, city, description):
    # Валидация входных данных
    name = validate_string_length(name, MAX_NAME_LENGTH, "name")
    phone = validate_string_length(phone, MAX_PHONE_LENGTH, "phone")
    city = validate_string_length(city, MAX_CITY_LENGTH, "city")
    description = validate_string_length(description, MAX_DESCRIPTION_LENGTH, "description")

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO clients (user_id, name, phone, city, description)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, phone, city, description))
        client_id = cursor.lastrowid
        conn.commit()
        logger.info(f"✅ Создан профиль клиента: ID={client_id}, User={user_id}, Имя={name}, Город={city}")


def get_worker_profile(user_id):
    """Возвращает профиль мастера по user_id"""
    with get_db_connection() as conn:

        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT w.*, u.telegram_id
            FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE w.user_id = ?
        """, (user_id,))
        return cursor.fetchone()


# Алиас для совместимости с кодом в handlers.py
def get_worker_by_user_id(user_id):
    """Алиас для get_worker_profile() - возвращает профиль мастера по user_id"""
    return get_worker_profile(user_id)


def get_client_profile(user_id):
    """Возвращает профиль заказчика по user_id"""
    with get_db_connection() as conn:
        
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
    with get_db_connection() as conn:
        
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM clients WHERE id = ?
        """, (client_id,))
        return cursor.fetchone()


# УДАЛЕНА ДУБЛИРУЮЩАЯСЯ ФУНКЦИЯ get_user_by_id() - используется версия из строки 429


# --- Рейтинг и отзывы ---

def update_user_rating(user_id, new_rating, role_to):
    """
    ИСПРАВЛЕНО: Использует атомарный UPDATE для предотвращения race conditions.
    Теперь вычисление нового рейтинга происходит внутри SQL запроса,
    что гарантирует консистентность даже при одновременных обновлениях.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if role_to == "worker":
            # Атомарный UPDATE: вычисление происходит в БД, не в Python
            cursor.execute("""
                UPDATE workers
                SET
                    rating = CASE
                        WHEN rating_count = 0 THEN ?
                        ELSE (rating * rating_count + ?) / (rating_count + 1)
                    END,
                    rating_count = rating_count + 1
                WHERE user_id = ?
            """, (new_rating, new_rating, user_id))

        elif role_to == "client":
            # Атомарный UPDATE для клиентов
            cursor.execute("""
                UPDATE clients
                SET
                    rating = CASE
                        WHEN rating_count = 0 THEN ?
                        ELSE (rating * rating_count + ?) / (rating_count + 1)
                    END,
                    rating_count = rating_count + 1
                WHERE user_id = ?
            """, (new_rating, new_rating, user_id))

        conn.commit()


def add_review(from_user_id, to_user_id, order_id, role_from, role_to, rating, comment):
    """
    Добавляет отзыв и обновляет рейтинг пользователя.
    Если роль получателя - worker, увеличивает счетчик verified_reviews.
    """
    with get_db_connection() as conn:
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

            # Увеличиваем счетчик проверенных отзывов для мастеров
            if role_to == "worker":
                increment_verified_reviews(to_user_id)

            return True
        except (sqlite3.IntegrityError, Exception) as e:
            print(f"⚠️ Ошибка при добавлении отзыва: {e}")
            return False


def get_reviews_for_user(user_id, role):
    """
    Получает все отзывы о пользователе.

    Args:
        user_id: ID пользователя
        role: Роль пользователя ('worker' или 'client')

    Returns:
        List of reviews with reviewer info
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем отзывы с информацией о том, кто оставил
        cursor.execute("""
            SELECT
                r.rating,
                r.comment,
                r.created_at,
                r.order_id,
                r.role_from,
                CASE
                    WHEN r.role_from = 'worker' THEN w.name
                    WHEN r.role_from = 'client' THEN c.name
                END as reviewer_name
            FROM reviews r
            LEFT JOIN workers w ON r.from_user_id = w.user_id AND r.role_from = 'worker'
            LEFT JOIN clients c ON r.from_user_id = c.user_id AND r.role_from = 'client'
            WHERE r.to_user_id = ? AND r.role_to = ?
            ORDER BY r.created_at DESC
        """, (user_id, role))

        return cursor.fetchall()


def check_review_exists(order_id, from_user_id):
    """
    Проверяет, оставил ли пользователь уже отзыв по этому заказу.

    Returns:
        bool: True если отзыв уже существует
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT COUNT(*) FROM reviews
            WHERE order_id = ? AND from_user_id = ?
        """, (order_id, from_user_id))

        count = cursor.fetchone()
        if USE_POSTGRES:
            return count['count'] > 0
        else:
            return count[0] > 0


def increment_verified_reviews(user_id):
    """
    Увеличивает счетчик проверенных отзывов для мастера.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE workers
            SET verified_reviews = verified_reviews + 1
            WHERE user_id = ?
        """, (user_id,))
        conn.commit()


def get_order_by_id(order_id):
    """
    Получает заказ по ID со всей информацией о клиенте.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT
                o.*,
                c.name as client_name,
                c.phone as client_phone,
                c.user_id as client_user_id,
                c.rating as client_rating,
                c.rating_count as client_rating_count
            FROM orders o
            JOIN clients c ON o.client_id = c.id
            WHERE o.id = ?
        """, (order_id,))
        return cursor.fetchone()


def update_order_status(order_id, new_status):
    """
    Обновляет статус заказа.

    Args:
        order_id: ID заказа
        new_status: Новый статус ('open', 'in_progress', 'completed', 'canceled')
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE orders
            SET status = ?
            WHERE id = ?
        """, (new_status, order_id))
        conn.commit()


def get_all_user_telegram_ids():
    """
    Получает все telegram_id пользователей для массовой рассылки.

    Returns:
        List of telegram_ids
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT telegram_id FROM users")
        results = cursor.fetchall()

        if USE_POSTGRES:
            return [row['telegram_id'] for row in results]
        else:
            return [row[0] for row in results]


def set_selected_worker(order_id, worker_id):
    """
    Устанавливает выбранного мастера для заказа и меняет статус на 'in_progress'.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE orders
            SET selected_worker_id = ?, status = 'in_progress'
            WHERE id = ?
        """, (worker_id, order_id))
        conn.commit()


def mark_order_completed_by_client(order_id):
    """
    Клиент подтверждает завершение заказа.
    Если мастер тоже подтвердил - меняет статус на 'completed'.

    Returns:
        bool: True если обе стороны подтвердили завершение
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Помечаем что клиент подтвердил
        cursor.execute("""
            UPDATE orders
            SET completed_by_client = 1
            WHERE id = ?
        """, (order_id,))

        # Проверяем подтвердил ли мастер
        cursor.execute("""
            SELECT completed_by_worker FROM orders WHERE id = ?
        """, (order_id,))
        row = cursor.fetchone()

        if row:
            if USE_POSTGRES:
                worker_completed = row['completed_by_worker']
            else:
                worker_completed = row[0]

            # Если обе стороны подтвердили - меняем статус
            if worker_completed:
                cursor.execute("""
                    UPDATE orders SET status = 'completed' WHERE id = ?
                """, (order_id,))
                conn.commit()
                logger.info(f"✅ Заказ {order_id} завершен: обе стороны подтвердили (клиент)")
                return True

        conn.commit()
        logger.info(f"📝 Заказ {order_id}: клиент подтвердил завершение, ожидается подтверждение мастера")
        return False


def mark_order_completed_by_worker(order_id):
    """
    Мастер подтверждает завершение заказа.
    Если клиент тоже подтвердил - меняет статус на 'completed'.

    Returns:
        bool: True если обе стороны подтвердили завершение
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Помечаем что мастер подтвердил
        cursor.execute("""
            UPDATE orders
            SET completed_by_worker = 1
            WHERE id = ?
        """, (order_id,))

        # Проверяем подтвердил ли клиент
        cursor.execute("""
            SELECT completed_by_client FROM orders WHERE id = ?
        """, (order_id,))
        row = cursor.fetchone()

        if row:
            if USE_POSTGRES:
                client_completed = row['completed_by_client']
            else:
                client_completed = row[0]

            # Если обе стороны подтвердили - меняем статус
            if client_completed:
                cursor.execute("""
                    UPDATE orders SET status = 'completed' WHERE id = ?
                """, (order_id,))
                conn.commit()
                logger.info(f"✅ Заказ {order_id} завершен: обе стороны подтвердили (мастер)")
                return True

        conn.commit()
        logger.info(f"📝 Заказ {order_id}: мастер подтвердил завершение, ожидается подтверждение клиента")
        return False


def get_worker_info_for_order(order_id):
    """
    Получает информацию о мастере, работающем над заказом.

    Returns:
        dict with worker info or None
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT
                w.id as worker_id,
                w.user_id,
                w.name,
                w.phone,
                w.rating,
                w.rating_count
            FROM orders o
            JOIN workers w ON o.selected_worker_id = w.id
            WHERE o.id = ?
        """, (order_id,))
        return cursor.fetchone()


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
    # Безопасный whitelist подход - используем словарь для маппинга
    allowed_fields = {
        "name": "name",
        "phone": "phone",
        "city": "city",
        "regions": "regions",
        "categories": "categories",
        "experience": "experience",
        "description": "description",
        "portfolio_photos": "portfolio_photos"
    }

    if field_name not in allowed_fields:
        raise ValueError(f"Недопустимое поле: {field_name}")

    # Валидация входных данных в зависимости от поля
    if field_name == "name":
        new_value = validate_string_length(new_value, MAX_NAME_LENGTH, "name")
    elif field_name == "phone":
        new_value = validate_string_length(new_value, MAX_PHONE_LENGTH, "phone")
    elif field_name in ["city", "regions"]:
        new_value = validate_string_length(new_value, MAX_CITY_LENGTH, field_name)
    elif field_name == "categories":
        new_value = validate_string_length(new_value, MAX_CATEGORY_LENGTH, "categories")
    elif field_name == "experience":
        new_value = validate_string_length(new_value, MAX_EXPERIENCE_LENGTH, "experience")
    elif field_name == "description":
        new_value = validate_string_length(new_value, MAX_DESCRIPTION_LENGTH, "description")

    # Используем безопасное имя поля из whitelist
    safe_field = allowed_fields[field_name]

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        # Безопасное построение запроса с явным whitelist
        query = f"UPDATE workers SET {safe_field} = ? WHERE user_id = ?"
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
    # Безопасный whitelist подход - используем словарь для маппинга
    allowed_fields = {
        "name": "name",
        "phone": "phone",
        "city": "city",
        "description": "description"
    }

    if field_name not in allowed_fields:
        raise ValueError(f"Недопустимое поле: {field_name}")

    # Валидация входных данных в зависимости от поля
    if field_name == "name":
        new_value = validate_string_length(new_value, MAX_NAME_LENGTH, "name")
    elif field_name == "phone":
        new_value = validate_string_length(new_value, MAX_PHONE_LENGTH, "phone")
    elif field_name == "city":
        new_value = validate_string_length(new_value, MAX_CITY_LENGTH, "city")
    elif field_name == "description":
        new_value = validate_string_length(new_value, MAX_DESCRIPTION_LENGTH, "description")

    # Используем безопасное имя поля из whitelist
    safe_field = allowed_fields[field_name]

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        # Безопасное построение запроса с явным whitelist
        query = f"UPDATE clients SET {safe_field} = ? WHERE user_id = ?"
        cursor.execute(query, (new_value, user_id))
        conn.commit()

        return cursor.rowcount > 0


# --- Поиск мастеров ---

def get_all_workers(city=None, category=None):
    """
    ИСПРАВЛЕНО: Использует точный поиск по категориям вместо LIKE.

    Получает список всех мастеров с фильтрами.

    Args:
        city: Фильтр по городу (опционально)
        category: Фильтр по категории (опционально)

    Returns:
        List of worker profiles with user info
    """
    with get_db_connection() as conn:

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
            # Точное совпадение города (без LIKE)
            query += " AND w.city = ?"
            params.append(city)

        if category:
            # ИСПРАВЛЕНО: Точный поиск по категории через worker_categories
            # Раньше: LIKE '%Электрика%' (находил 'Неэлектрика')
            # Теперь: EXISTS с точным совпадением
            query += """
                AND EXISTS (
                    SELECT 1 FROM worker_categories wc
                    WHERE wc.worker_id = w.id AND wc.category = ?
                )
            """
            params.append(category)

        query += " ORDER BY w.rating DESC, w.rating_count DESC"

        cursor.execute(query, params)
        return cursor.fetchall()


def get_worker_by_id(worker_id):
    """Получает профиль мастера по ID"""
    with get_db_connection() as conn:
        
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


# --- Категории мастеров (новая нормализованная система) ---

def add_worker_categories(worker_id, categories_list):
    """
    Добавляет категории для мастера в таблицу worker_categories.

    Args:
        worker_id: ID мастера
        categories_list: список категорий ["Электрика", "Сантехника"]
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        for category in categories_list:
            if not category or not category.strip():
                continue

            try:
                cursor.execute("""
                    INSERT INTO worker_categories (worker_id, category)
                    VALUES (?, ?)
                """, (worker_id, category.strip()))
            except:
                # Игнорируем дубликаты (UNIQUE constraint)
                pass

        conn.commit()


def get_worker_categories(worker_id):
    """
    Получает все категории мастера.

    Returns:
        Список категорий: ["Электрика", "Сантехника"]
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT category FROM worker_categories
            WHERE worker_id = ?
            ORDER BY category
        """, (worker_id,))

        return [row[0] for row in cursor.fetchall()]


def remove_worker_category(worker_id, category):
    """Удаляет категорию у мастера"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            DELETE FROM worker_categories
            WHERE worker_id = ? AND category = ?
        """, (worker_id, category))
        conn.commit()


def clear_worker_categories(worker_id):
    """Удаляет все категории мастера"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            DELETE FROM worker_categories
            WHERE worker_id = ?
        """, (worker_id,))
        conn.commit()


def migrate_add_order_photos():
    """Добавляет колонку photos в таблицу orders"""
    # Для PostgreSQL миграции не нужны - таблицы создаются через init_db()
    if USE_POSTGRES:
        print("✅ Используется PostgreSQL, миграция не требуется")
        return

    with get_db_connection() as conn:
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

    with get_db_connection() as conn:
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


def migrate_add_cascading_deletes():
    """
    Добавляет cascading deletes для PostgreSQL.
    При удалении пользователя автоматически удаляются все связанные записи.
    """
    if not USE_POSTGRES:
        print("✅ SQLite не требует миграции cascading deletes")
        return

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Для PostgreSQL нужно пересоздать foreign keys с ON DELETE CASCADE
            # Сначала удаляем старые ограничения, затем создаем новые

            print("📝 Добавление cascading deletes для PostgreSQL...")

            # Workers: user_id -> users(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'workers_user_id_fkey'
                    ) THEN
                        ALTER TABLE workers DROP CONSTRAINT workers_user_id_fkey;
                    END IF;
                    ALTER TABLE workers ADD CONSTRAINT workers_user_id_fkey
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                END $$;
            """)

            # Clients: user_id -> users(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'clients_user_id_fkey'
                    ) THEN
                        ALTER TABLE clients DROP CONSTRAINT clients_user_id_fkey;
                    END IF;
                    ALTER TABLE clients ADD CONSTRAINT clients_user_id_fkey
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                END $$;
            """)

            # Orders: client_id -> clients(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'orders_client_id_fkey'
                    ) THEN
                        ALTER TABLE orders DROP CONSTRAINT orders_client_id_fkey;
                    END IF;
                    ALTER TABLE orders ADD CONSTRAINT orders_client_id_fkey
                        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE;
                END $$;
            """)

            # Bids: order_id -> orders(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'bids_order_id_fkey'
                    ) THEN
                        ALTER TABLE bids DROP CONSTRAINT bids_order_id_fkey;
                    END IF;
                    ALTER TABLE bids ADD CONSTRAINT bids_order_id_fkey
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE;
                END $$;
            """)

            # Bids: worker_id -> workers(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'bids_worker_id_fkey'
                    ) THEN
                        ALTER TABLE bids DROP CONSTRAINT bids_worker_id_fkey;
                    END IF;
                    ALTER TABLE bids ADD CONSTRAINT bids_worker_id_fkey
                        FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE;
                END $$;
            """)

            # Reviews: ON DELETE CASCADE для всех внешних ключей
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'reviews_from_user_id_fkey'
                    ) THEN
                        ALTER TABLE reviews DROP CONSTRAINT reviews_from_user_id_fkey;
                    END IF;
                    ALTER TABLE reviews ADD CONSTRAINT reviews_from_user_id_fkey
                        FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE;

                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'reviews_to_user_id_fkey'
                    ) THEN
                        ALTER TABLE reviews DROP CONSTRAINT reviews_to_user_id_fkey;
                    END IF;
                    ALTER TABLE reviews ADD CONSTRAINT reviews_to_user_id_fkey
                        FOREIGN KEY (to_user_id) REFERENCES users(id) ON DELETE CASCADE;

                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'reviews_order_id_fkey'
                    ) THEN
                        ALTER TABLE reviews DROP CONSTRAINT reviews_order_id_fkey;
                    END IF;
                    ALTER TABLE reviews ADD CONSTRAINT reviews_order_id_fkey
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE;
                END $$;
            """)

            logger.info("✅ Cascading deletes успешно добавлены!")

        except Exception as e:
            logger.warning(f"⚠️ Предупреждение при добавлении cascading deletes: {e}", exc_info=True)
            # Не пробрасываем ошибку - миграция не критична если constraint уже существует


def migrate_add_order_completion_tracking():
    """
    Добавляет поля для отслеживания завершения заказа обеими сторонами.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                print("📝 Добавление полей отслеживания завершения для PostgreSQL...")

                # Проверяем и добавляем поля если их нет
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'orders' AND column_name = 'selected_worker_id'
                        ) THEN
                            ALTER TABLE orders ADD COLUMN selected_worker_id INTEGER;
                            ALTER TABLE orders ADD CONSTRAINT orders_selected_worker_id_fkey
                                FOREIGN KEY (selected_worker_id) REFERENCES workers(id) ON DELETE SET NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'orders' AND column_name = 'completed_by_client'
                        ) THEN
                            ALTER TABLE orders ADD COLUMN completed_by_client INTEGER DEFAULT 0;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'orders' AND column_name = 'completed_by_worker'
                        ) THEN
                            ALTER TABLE orders ADD COLUMN completed_by_worker INTEGER DEFAULT 0;
                        END IF;
                    END $$;
                """)
                conn.commit()
                print("✅ Поля отслеживания завершения успешно добавлены!")

            else:
                # Для SQLite проверяем существование колонок
                cursor.execute("PRAGMA table_info(orders)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'selected_worker_id' not in columns:
                    print("📝 Добавление поля selected_worker_id...")
                    cursor.execute("ALTER TABLE orders ADD COLUMN selected_worker_id INTEGER")

                if 'completed_by_client' not in columns:
                    print("📝 Добавление поля completed_by_client...")
                    cursor.execute("ALTER TABLE orders ADD COLUMN completed_by_client INTEGER DEFAULT 0")

                if 'completed_by_worker' not in columns:
                    print("📝 Добавление поля completed_by_worker...")
                    cursor.execute("ALTER TABLE orders ADD COLUMN completed_by_worker INTEGER DEFAULT 0")

                conn.commit()
                print("✅ Поля отслеживания завершения успешно добавлены!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении полей отслеживания завершения: {e}")


def migrate_add_profile_photo():
    """
    Добавляет поле profile_photo для фото профиля мастера (лицо).
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                print("📝 Добавление поля profile_photo для PostgreSQL...")

                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'workers' AND column_name = 'profile_photo'
                        ) THEN
                            ALTER TABLE workers ADD COLUMN profile_photo TEXT;
                        END IF;
                    END $$;
                """)
                conn.commit()
                print("✅ Поле profile_photo успешно добавлено!")

            else:
                # Для SQLite проверяем существование колонки
                cursor.execute("PRAGMA table_info(workers)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'profile_photo' not in columns:
                    print("📝 Добавление поля profile_photo...")
                    cursor.execute("ALTER TABLE workers ADD COLUMN profile_photo TEXT")
                    conn.commit()
                    print("✅ Поле profile_photo успешно добавлено!")
                else:
                    print("✅ Поле profile_photo уже существует")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении поля profile_photo: {e}")


def migrate_add_premium_features():
    """
    Добавляет поля для premium функций:
    - premium_enabled (глобальный флаг в settings)
    - is_premium_order (для orders)
    - is_premium_worker (для workers)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Создаём таблицу settings если её нет
            if USE_POSTGRES:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key VARCHAR(100) PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

            # Устанавливаем premium_enabled = false по умолчанию
            cursor.execute("""
                INSERT OR IGNORE INTO settings (key, value)
                VALUES ('premium_enabled', 'false')
            """)

            # Добавляем поля для premium в orders
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'orders' AND column_name = 'is_premium'
                        ) THEN
                            ALTER TABLE orders ADD COLUMN is_premium BOOLEAN DEFAULT FALSE;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'orders' AND column_name = 'premium_until'
                        ) THEN
                            ALTER TABLE orders ADD COLUMN premium_until TIMESTAMP;
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(orders)")
                order_columns = [column[1] for column in cursor.fetchall()]

                if 'is_premium' not in order_columns:
                    cursor.execute("ALTER TABLE orders ADD COLUMN is_premium INTEGER DEFAULT 0")

                if 'premium_until' not in order_columns:
                    cursor.execute("ALTER TABLE orders ADD COLUMN premium_until TIMESTAMP")

            # Добавляем поля для premium в workers
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'workers' AND column_name = 'is_premium'
                        ) THEN
                            ALTER TABLE workers ADD COLUMN is_premium BOOLEAN DEFAULT FALSE;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'workers' AND column_name = 'premium_until'
                        ) THEN
                            ALTER TABLE workers ADD COLUMN premium_until TIMESTAMP;
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(workers)")
                worker_columns = [column[1] for column in cursor.fetchall()]

                if 'is_premium' not in worker_columns:
                    cursor.execute("ALTER TABLE workers ADD COLUMN is_premium INTEGER DEFAULT 0")

                if 'premium_until' not in worker_columns:
                    cursor.execute("ALTER TABLE workers ADD COLUMN premium_until TIMESTAMP")

            conn.commit()
            print("✅ Premium features migration completed successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении premium полей: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_chat_system():
    """
    Создаёт таблицы для системы чата между клиентом и мастером
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Таблица чатов
            if USE_POSTGRES:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        id SERIAL PRIMARY KEY,
                        order_id INTEGER NOT NULL,
                        client_user_id INTEGER NOT NULL,
                        worker_user_id INTEGER NOT NULL,
                        bid_id INTEGER NOT NULL,
                        status VARCHAR(50) DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_message_at TIMESTAMP,
                        worker_confirmed BOOLEAN DEFAULT FALSE,
                        worker_confirmed_at TIMESTAMP,
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                        FOREIGN KEY (bid_id) REFERENCES bids(id) ON DELETE CASCADE
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id SERIAL PRIMARY KEY,
                        chat_id INTEGER NOT NULL,
                        sender_user_id INTEGER NOT NULL,
                        sender_role VARCHAR(20) NOT NULL,
                        message_text TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_read BOOLEAN DEFAULT FALSE,
                        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        order_id INTEGER NOT NULL,
                        client_user_id INTEGER NOT NULL,
                        worker_user_id INTEGER NOT NULL,
                        bid_id INTEGER NOT NULL,
                        status TEXT DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_message_at TIMESTAMP,
                        worker_confirmed INTEGER DEFAULT 0,
                        worker_confirmed_at TIMESTAMP,
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                        FOREIGN KEY (bid_id) REFERENCES bids(id) ON DELETE CASCADE
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        sender_user_id INTEGER NOT NULL,
                        sender_role TEXT NOT NULL,
                        message_text TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_read INTEGER DEFAULT 0,
                        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
                    )
                """)

            conn.commit()
            print("✅ Chat system tables created successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при создании таблиц чата: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_transactions():
    """
    Создаёт таблицу для истории транзакций (платежей клиентов)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        order_id INTEGER,
                        bid_id INTEGER,
                        transaction_type VARCHAR(50) NOT NULL,
                        amount DECIMAL(10, 2) NOT NULL,
                        currency VARCHAR(10) DEFAULT 'BYN',
                        status VARCHAR(50) DEFAULT 'pending',
                        payment_method VARCHAR(50),
                        description TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
                        FOREIGN KEY (bid_id) REFERENCES bids(id) ON DELETE SET NULL
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        order_id INTEGER,
                        bid_id INTEGER,
                        transaction_type TEXT NOT NULL,
                        amount REAL NOT NULL,
                        currency TEXT DEFAULT 'BYN',
                        status TEXT DEFAULT 'pending',
                        payment_method TEXT,
                        description TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
                        FOREIGN KEY (bid_id) REFERENCES bids(id) ON DELETE SET NULL
                    )
                """)

            conn.commit()
            print("✅ Transactions table created successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при создании таблицы транзакций: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_notification_settings():
    """
    Добавляет поле для управления уведомлениями мастеров:
    - notifications_enabled (по умолчанию TRUE - уведомления включены)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'workers' AND column_name = 'notifications_enabled'
                        ) THEN
                            ALTER TABLE workers ADD COLUMN notifications_enabled BOOLEAN DEFAULT TRUE;
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(workers)")
                worker_columns = [column[1] for column in cursor.fetchall()]

                if 'notifications_enabled' not in worker_columns:
                    cursor.execute("ALTER TABLE workers ADD COLUMN notifications_enabled INTEGER DEFAULT 1")

            conn.commit()
            print("✅ Notification settings migration completed successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении настроек уведомлений: {e}")
            import traceback
            traceback.print_exc()


def migrate_normalize_categories():
    """
    ИСПРАВЛЕНИЕ: Создает отдельную таблицу для категорий мастеров.

    ПРОБЛЕМА: categories LIKE '%Электрика%' находит 'Неэлектрика'
    РЕШЕНИЕ: Отдельная таблица worker_categories с точным поиском

    Создает:
    1. Таблицу worker_categories (worker_id, category)
    2. Переносит данные из workers.categories
    3. Создает индексы для быстрого поиска
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Проверяем существует ли уже таблица
            if USE_POSTGRES:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'worker_categories'
                    )
                """)
                table_exists = cursor.fetchone()[0]
            else:
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='worker_categories'
                """)
                table_exists = cursor.fetchone() is not None

            if table_exists:
                print("ℹ️  Таблица worker_categories уже существует, пропускаем миграцию")
                return

            # Создаем таблицу worker_categories
            if USE_POSTGRES:
                cursor.execute("""
                    CREATE TABLE worker_categories (
                        id SERIAL PRIMARY KEY,
                        worker_id INTEGER NOT NULL,
                        category VARCHAR(100) NOT NULL,
                        FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE,
                        UNIQUE (worker_id, category)
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS worker_categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        worker_id INTEGER NOT NULL,
                        category TEXT NOT NULL,
                        FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE,
                        UNIQUE (worker_id, category)
                    )
                """)

            # Переносим существующие категории из workers.categories
            cursor.execute("SELECT id, categories FROM workers WHERE categories IS NOT NULL AND categories != ''")
            workers = cursor.fetchall()

            migrated_count = 0
            for worker in workers:
                worker_id = worker[0]
                categories_str = worker[1]

                if not categories_str:
                    continue

                # Разбиваем строку "Электрика, Сантехника" на список
                categories = [cat.strip() for cat in categories_str.split(',') if cat.strip()]

                for category in categories:
                    try:
                        cursor.execute("""
                            INSERT INTO worker_categories (worker_id, category)
                            VALUES (?, ?)
                        """, (worker_id, category))
                        migrated_count += 1
                    except:
                        # Пропускаем дубликаты
                        pass

            # Создаем индексы для быстрого поиска
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_worker_categories_worker
                ON worker_categories(worker_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_worker_categories_category
                ON worker_categories(category)
            """)

            conn.commit()
            print(f"✅ Категории нормализованы! Перенесено {migrated_count} категорий")
            print("   Теперь поиск будет точным, без ложных совпадений")

        except Exception as e:
            print(f"⚠️  Ошибка при нормализации категорий: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_moderation():
    """
    Добавляет поля для модерации пользователей:
    - is_banned (флаг бана)
    - ban_reason (причина бана)
    - banned_at (дата бана)
    - banned_by (кто забанил)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'users' AND column_name = 'is_banned'
                        ) THEN
                            ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'users' AND column_name = 'ban_reason'
                        ) THEN
                            ALTER TABLE users ADD COLUMN ban_reason TEXT;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'users' AND column_name = 'banned_at'
                        ) THEN
                            ALTER TABLE users ADD COLUMN banned_at TIMESTAMP;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'users' AND column_name = 'banned_by'
                        ) THEN
                            ALTER TABLE users ADD COLUMN banned_by VARCHAR(100);
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(users)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'is_banned' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")

                if 'ban_reason' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")

                if 'banned_at' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN banned_at TIMESTAMP")

                if 'banned_by' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN banned_by TEXT")

            conn.commit()
            print("✅ Moderation fields migration completed successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении модерационных полей: {e}")
            import traceback
            traceback.print_exc()


# === CHAT SYSTEM HELPERS ===

def create_chat(order_id, client_user_id, worker_user_id, bid_id):
    """Создаёт чат между клиентом и мастером"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO chats (order_id, client_user_id, worker_user_id, bid_id, created_at, last_message_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (order_id, client_user_id, worker_user_id, bid_id, datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        return cursor.lastrowid


def get_chat_by_order_and_bid(order_id, bid_id):
    """Получает чат по заказу и отклику"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM chats
            WHERE order_id = ? AND bid_id = ?
        """, (order_id, bid_id))
        return cursor.fetchone()


def get_chat_by_id(chat_id):
    """Получает чат по ID"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
        return cursor.fetchone()


def get_user_chats(user_id):
    """Получает все чаты пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT c.*, o.description as order_description
            FROM chats c
            JOIN orders o ON c.order_id = o.id
            WHERE c.client_user_id = ? OR c.worker_user_id = ?
            ORDER BY c.last_message_at DESC
        """, (user_id, user_id))
        return cursor.fetchall()


def send_message(chat_id, sender_user_id, sender_role, message_text):
    """Отправляет сообщение в чат"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Добавляем сообщение
        cursor.execute("""
            INSERT INTO messages (chat_id, sender_user_id, sender_role, message_text, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, sender_user_id, sender_role, message_text, datetime.now().isoformat()))

        # Обновляем время последнего сообщения в чате
        cursor.execute("""
            UPDATE chats
            SET last_message_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), chat_id))

        conn.commit()
        return cursor.lastrowid


def get_chat_messages(chat_id, limit=50):
    """Получает сообщения чата"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM messages
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (chat_id, limit))
        return cursor.fetchall()


def mark_messages_as_read(chat_id, user_id):
    """Отмечает сообщения как прочитанные для пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE messages
            SET is_read = 1
            WHERE chat_id = ? AND sender_user_id != ?
        """, (chat_id, user_id))
        conn.commit()


def get_unread_messages_count(chat_id, user_id):
    """Получает количество непрочитанных сообщений"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT COUNT(*) FROM messages
            WHERE chat_id = ? AND sender_user_id != ? AND is_read = 0
        """, (chat_id, user_id))
        return cursor.fetchone()[0]


def confirm_worker_in_chat(chat_id):
    """Мастер подтверждает готовность работать (первое сообщение = подтверждение)"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE chats
            SET worker_confirmed = 1, worker_confirmed_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), chat_id))
        conn.commit()


def is_worker_confirmed(chat_id):
    """Проверяет подтвердил ли мастер готовность"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT worker_confirmed FROM chats WHERE id = ?", (chat_id,))
        result = cursor.fetchone()
        return bool(result[0]) if result else False


# === TRANSACTION HELPERS ===

def create_transaction(user_id, order_id, bid_id, transaction_type, amount, currency='BYN', payment_method='test', description=''):
    """Создаёт транзакцию"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO transactions
            (user_id, order_id, bid_id, transaction_type, amount, currency, status, payment_method, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)
        """, (user_id, order_id, bid_id, transaction_type, amount, currency, payment_method, description, datetime.now().isoformat()))
        conn.commit()
        return cursor.lastrowid


def get_user_transactions(user_id):
    """Получает историю транзакций пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
        return cursor.fetchall()


def get_transaction_by_order_bid(order_id, bid_id):
    """Проверяет была ли оплата за доступ к мастеру"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM transactions
            WHERE order_id = ? AND bid_id = ? AND status = 'completed'
        """, (order_id, bid_id))
        return cursor.fetchone()


def get_expired_chats(hours=24):
    """
    Получает чаты где мастер не ответил в течение заданного времени

    Args:
        hours: количество часов для проверки (по умолчанию 24)

    Returns:
        Список чатов где worker_confirmed = FALSE и прошло более hours часов с created_at
    """
    from datetime import datetime, timedelta

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        expiration_time = datetime.now() - timedelta(hours=hours)

        cursor.execute("""
            SELECT * FROM chats
            WHERE worker_confirmed = 0
            AND created_at < ?
        """, (expiration_time.isoformat(),))

        return cursor.fetchall()


def mark_chat_as_expired(chat_id):
    """Помечает чат как просроченный (мастер не ответил вовремя)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        # Можно добавить поле expired_at или is_expired, но пока просто оставим
        # Чат будет считаться просроченным по факту что worker_confirmed = 0 и прошло 24 часа
        pass


# === NOTIFICATION SETTINGS HELPERS ===

def are_notifications_enabled(user_id):
    """
    Проверяет включены ли уведомления для мастера.

    Args:
        user_id: ID пользователя в таблице users

    Returns:
        True если уведомления включены или настройка не найдена (по умолчанию включены)
        False если уведомления отключены
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT notifications_enabled
            FROM workers
            WHERE user_id = ?
        """, (user_id,))
        result = cursor.fetchone()

        # Если запись не найдена или поле не существует - по умолчанию включены
        if not result:
            return True

        # SQLite хранит boolean как INTEGER (1 или 0), PostgreSQL как BOOLEAN
        return bool(result[0]) if result[0] is not None else True


def set_notifications_enabled(user_id, enabled):
    """
    Включает или отключает уведомления для мастера.

    Args:
        user_id: ID пользователя в таблице users
        enabled: True для включения, False для отключения

    Returns:
        True если обновление успешно, False если мастер не найден
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Для совместимости с SQLite и PostgreSQL
        value = 1 if enabled else 0 if not USE_POSTGRES else enabled

        cursor.execute("""
            UPDATE workers
            SET notifications_enabled = ?
            WHERE user_id = ?
        """, (value, user_id))

        conn.commit()
        return cursor.rowcount > 0


# === PREMIUM FEATURES HELPERS ===

def is_premium_enabled():
    """Проверяет включены ли premium функции глобально"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT value FROM settings WHERE key = 'premium_enabled'")
        result = cursor.fetchone()
        return result and result[0] == 'true'


def set_premium_enabled(enabled):
    """Включает/выключает premium функции глобально"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        value = 'true' if enabled else 'false'
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES ('premium_enabled', ?, datetime('now'))
        """, (value,))
        conn.commit()


def get_setting(key, default=None):
    """Получает значение настройки"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else default


def set_setting(key, value):
    """Устанавливает значение настройки"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
        """, (key, value))
        conn.commit()


# === MODERATION HELPERS ===

def is_user_banned(telegram_id):
    """Проверяет забанен ли пользователь"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT is_banned FROM users WHERE telegram_id = ?
        """, (telegram_id,))
        result = cursor.fetchone()
        if result:
            return bool(result[0])
        return False


def ban_user(telegram_id, reason, banned_by):
    """Банит пользователя"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE users
            SET is_banned = 1,
                ban_reason = ?,
                banned_at = ?,
                banned_by = ?
            WHERE telegram_id = ?
        """, (reason, datetime.now().isoformat(), banned_by, telegram_id))
        conn.commit()
        return cursor.rowcount > 0


def unban_user(telegram_id):
    """Разбанивает пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE users
            SET is_banned = 0,
                ban_reason = NULL,
                banned_at = NULL,
                banned_by = NULL
            WHERE telegram_id = ?
        """, (telegram_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_banned_users():
    """Получает список всех забаненных пользователей"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT telegram_id, ban_reason, banned_at, banned_by
            FROM users
            WHERE is_banned = 1
            ORDER BY banned_at DESC
        """)
        return cursor.fetchall()


# === ANALYTICS HELPERS ===

def get_analytics_stats():
    """Получает основную статистику для аналитики"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        stats = {}

        # Всего пользователей
        cursor.execute("SELECT COUNT(*) FROM users")
        stats['total_users'] = cursor.fetchone()[0]

        # Забаненных пользователей
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        stats['banned_users'] = cursor.fetchone()[0]

        # Мастеров
        cursor.execute("SELECT COUNT(*) FROM workers")
        stats['total_workers'] = cursor.fetchone()[0]

        # Клиентов
        cursor.execute("SELECT COUNT(*) FROM clients")
        stats['total_clients'] = cursor.fetchone()[0]

        # Заказов (всего)
        cursor.execute("SELECT COUNT(*) FROM orders")
        stats['total_orders'] = cursor.fetchone()[0]

        # Активных заказов
        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'open'")
        stats['active_orders'] = cursor.fetchone()[0]

        # Завершённых заказов
        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
        stats['completed_orders'] = cursor.fetchone()[0]

        # Откликов (всего)
        cursor.execute("SELECT COUNT(*) FROM bids")
        stats['total_bids'] = cursor.fetchone()[0]

        # Активных откликов
        cursor.execute("SELECT COUNT(*) FROM bids WHERE status = 'active'")
        stats['active_bids'] = cursor.fetchone()[0]

        # Отзывов
        cursor.execute("SELECT COUNT(*) FROM reviews")
        stats['total_reviews'] = cursor.fetchone()[0]

        # Premium статус
        stats['premium_enabled'] = is_premium_enabled()

        return stats


def create_indexes():
    """
    Создает индексы для оптимизации производительности запросов.
    Должна вызываться после init_db().
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Индексы для таблицы users
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")

            # Индексы для таблицы workers
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_user_id ON workers(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_city ON workers(city)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_rating ON workers(rating DESC)")

            # Индексы для таблицы clients
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clients_user_id ON clients(user_id)")

            # Индексы для таблицы orders
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_client_id ON orders(client_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_city ON orders(city)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_category ON orders(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC)")
            # Composite index для часто используемого запроса
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status_category ON orders(status, category)")

            # Индексы для таблицы bids
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bids_order_id ON bids(order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bids_worker_id ON bids(worker_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bids_status ON bids(status)")
            # Composite index для проверки существования отклика
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bids_order_worker ON bids(order_id, worker_id)")

            # Индексы для таблицы reviews
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_from_user ON reviews(from_user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_to_user ON reviews(to_user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_order_id ON reviews(order_id)")

            conn.commit()
            print("✅ Индексы успешно созданы для оптимизации производительности")

        except Exception as e:
            print(f"⚠️  Предупреждение при создании индексов: {e}")

def create_order(client_id, city, categories, description, photos, budget_type="none", budget_value=0):
    """Создаёт новый заказ"""
    # Rate limiting: проверяем лимит заказов
    allowed, remaining_seconds = _rate_limiter.is_allowed(client_id, "create_order", RATE_LIMIT_ORDERS_PER_HOUR)
    if not allowed:
        minutes = remaining_seconds // 60
        raise ValueError(f"❌ Превышен лимит создания заказов. Попробуйте через {minutes} мин.")

    # Валидация входных данных
    city = validate_string_length(city, MAX_CITY_LENGTH, "city")
    description = validate_string_length(description, MAX_DESCRIPTION_LENGTH, "description")

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Преобразуем список категорий в строку
        categories_str = ", ".join(categories) if isinstance(categories, list) else categories
        categories_str = validate_string_length(categories_str, MAX_CATEGORY_LENGTH, "categories")

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
        order_id = cursor.lastrowid
        logger.info(f"✅ Создан заказ: ID={order_id}, Клиент={client_id}, Город={city}, Категории={categories_str}")
        return order_id


def get_orders_by_category(category, page=1, per_page=10):
    """
    Получает открытые заказы по категории с пагинацией.

    Args:
        category: Категория заказа
        page: Номер страницы (начиная с 1)
        per_page: Количество заказов на странице

    Returns:
        tuple: (orders, total_count, has_next_page)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем общее количество заказов
        cursor.execute("""
            SELECT COUNT(*) FROM orders o
            WHERE o.status = 'open' AND o.category LIKE ?
        """, (f"%{category}%",))
        total_count = cursor.fetchone()[0] if not USE_POSTGRES else cursor.fetchone()['count']

        # Получаем заказы для текущей страницы
        offset = (page - 1) * per_page
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
            LIMIT ? OFFSET ?
        """, (f"%{category}%", per_page, offset))

        orders = cursor.fetchall()
        has_next_page = (offset + per_page) < total_count

        return orders, total_count, has_next_page


def get_orders_by_categories(categories_list, per_page=30):
    """
    ИСПРАВЛЕНИЕ: Получает заказы для НЕСКОЛЬКИХ категорий ОДНИМ запросом.

    Раньше: 5 категорий = 5 SQL запросов (N+1 проблема)
    Теперь: 5 категорий = 1 SQL запрос

    Args:
        categories_list: Список категорий ["Электрика", "Сантехника"]
        per_page: Максимум заказов (по умолчанию 30)

    Returns:
        Список заказов, отсортированных по дате (новые первые)
    """
    if not categories_list:
        return []

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Создаем условие WHERE с OR для каждой категории
        # Используем точный поиск через LIKE для каждой категории
        where_conditions = []
        params = []

        for category in categories_list:
            if category and category.strip():
                where_conditions.append("o.category LIKE ?")
                params.append(f"%{category.strip()}%")

        if not where_conditions:
            return []

        where_clause = " OR ".join(where_conditions)

        # Один запрос для всех категорий
        query = f"""
            SELECT DISTINCT
                o.*,
                c.name as client_name,
                c.rating as client_rating,
                c.rating_count as client_rating_count
            FROM orders o
            JOIN clients c ON o.client_id = c.id
            WHERE o.status = 'open'
            AND ({where_clause})
            ORDER BY o.created_at DESC
            LIMIT ?
        """
        params.append(per_page)

        cursor.execute(query, params)
        return cursor.fetchall()


def get_client_orders(client_id, page=1, per_page=10):
    """
    Получает заказы клиента с пагинацией.

    Args:
        client_id: ID клиента
        page: Номер страницы (начиная с 1)
        per_page: Количество заказов на странице

    Returns:
        tuple: (orders, total_count, has_next_page)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем общее количество заказов
        cursor.execute("SELECT COUNT(*) FROM orders WHERE client_id = ?", (client_id,))
        total_count = cursor.fetchone()[0] if not USE_POSTGRES else cursor.fetchone()['count']

        # Получаем заказы для текущей страницы
        offset = (page - 1) * per_page
        cursor.execute("""
            SELECT * FROM orders
            WHERE client_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (client_id, per_page, offset))

        orders = cursor.fetchall()
        has_next_page = (offset + per_page) < total_count

        return orders, total_count, has_next_page


def get_order_by_id(order_id):
    """Получает заказ по ID"""
    with get_db_connection() as conn:

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


def update_order_status(order_id, new_status):
    """Обновляет статус заказа"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE orders
            SET status = ?
            WHERE id = ?
        """, (new_status, order_id))
        conn.commit()
        success = cursor.rowcount > 0
        if success:
            logger.info(f"✅ Обновлен статус заказа: ID={order_id}, Новый статус={new_status}")
        else:
            logger.warning(f"⚠️ Заказ {order_id} не найден для обновления статуса")
        return success


def cancel_order(order_id, cancelled_by_user_id, reason=""):
    """
    НОВОЕ: Отменяет заказ клиентом.

    Args:
        order_id: ID заказа
        cancelled_by_user_id: ID пользователя который отменяет
        reason: Причина отмены (опционально)

    Returns:
        dict: {
            'success': bool,
            'message': str,
            'notified_workers': list  # ID мастеров которым отправлено уведомление
        }
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Проверяем существование заказа и права на отмену
        cursor.execute("""
            SELECT o.*, c.user_id as client_user_id
            FROM orders o
            JOIN clients c ON o.client_id = c.id
            WHERE o.id = ?
        """, (order_id,))

        order = cursor.fetchone()
        if not order:
            return {'success': False, 'message': 'Заказ не найден', 'notified_workers': []}

        order_dict = dict(order)

        # Проверка прав: только владелец может отменить
        if order_dict['client_user_id'] != cancelled_by_user_id:
            return {'success': False, 'message': 'Нет прав на отмену этого заказа', 'notified_workers': []}

        # Проверка статуса: можно отменить только open или waiting_master_confirmation
        if order_dict['status'] not in ('open', 'waiting_master_confirmation'):
            return {
                'success': False,
                'message': f"Нельзя отменить заказ в статусе '{order_dict['status']}'",
                'notified_workers': []
            }

        # Обновляем статус заказа
        cursor.execute("""
            UPDATE orders
            SET status = 'cancelled'
            WHERE id = ?
        """, (order_id,))

        # Получаем список мастеров которые откликнулись (для уведомления)
        cursor.execute("""
            SELECT DISTINCT w.user_id
            FROM bids b
            JOIN workers w ON b.worker_id = w.id
            WHERE b.order_id = ? AND b.status IN ('pending', 'selected')
        """, (order_id,))

        worker_user_ids = [row[0] for row in cursor.fetchall()]

        # Отмечаем все отклики как rejected
        cursor.execute("""
            UPDATE bids
            SET status = 'rejected'
            WHERE order_id = ?
        """, (order_id,))

        conn.commit()

        logger.info(f"Заказ {order_id} отменен пользователем {cancelled_by_user_id}. Причина: {reason}")

        return {
            'success': True,
            'message': 'Заказ успешно отменен',
            'notified_workers': worker_user_ids
        }


def check_expired_orders():
    """
    НОВОЕ: Проверяет и обрабатывает заказы с истекшим дедлайном.

    Автоматически находит заказы, у которых:
    - deadline прошел (deadline < now)
    - статус 'open' или 'waiting_master_confirmation'

    Для найденных заказов:
    - Меняет статус на 'expired'
    - Отклоняет все активные отклики
    - Возвращает информацию для отправки уведомлений

    Returns:
        list: Список словарей с информацией о просроченных заказах:
            [
                {
                    'order_id': int,
                    'client_user_id': int,
                    'worker_user_ids': [int, ...],
                    'title': str
                },
                ...
            ]
    """
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Находим просроченные заказы
        now = datetime.now().isoformat()

        cursor.execute("""
            SELECT o.id, o.title, o.deadline, c.user_id as client_user_id
            FROM orders o
            JOIN clients c ON o.client_id = c.id
            WHERE o.deadline IS NOT NULL
            AND o.deadline != ''
            AND o.deadline < ?
            AND o.status IN ('open', 'waiting_master_confirmation')
        """, (now,))

        expired_orders = cursor.fetchall()

        if not expired_orders:
            logger.debug("Просроченных заказов не найдено")
            return []

        result = []

        for order_row in expired_orders:
            order_id = order_row[0]
            title = order_row[1]
            client_user_id = order_row[3]

            # Получаем всех мастеров, которые откликнулись
            cursor.execute("""
                SELECT DISTINCT w.user_id
                FROM bids b
                JOIN workers w ON b.worker_id = w.id
                WHERE b.order_id = ? AND b.status IN ('pending', 'selected')
            """, (order_id,))

            worker_rows = cursor.fetchall()
            worker_user_ids = [row[0] for row in worker_rows]

            # Обновляем статус заказа
            cursor.execute("""
                UPDATE orders
                SET status = 'expired'
                WHERE id = ?
            """, (order_id,))

            # Отклоняем все активные отклики
            cursor.execute("""
                UPDATE bids
                SET status = 'rejected'
                WHERE order_id = ? AND status IN ('pending', 'selected')
            """, (order_id,))

            logger.info(f"Заказ {order_id} истек по дедлайну. Клиент: {client_user_id}, Мастеров: {len(worker_user_ids)}")

            result.append({
                'order_id': order_id,
                'client_user_id': client_user_id,
                'worker_user_ids': worker_user_ids,
                'title': title
            })

        conn.commit()

        logger.info(f"Обработано просроченных заказов: {len(result)}")
        return result


def create_bid(order_id, worker_id, proposed_price, currency, comment=""):
    """Создаёт отклик мастера на заказ"""
    # Rate limiting: проверяем лимит откликов
    allowed, remaining_seconds = _rate_limiter.is_allowed(worker_id, "create_bid", RATE_LIMIT_BIDS_PER_HOUR)
    if not allowed:
        minutes = remaining_seconds // 60
        raise ValueError(f"❌ Превышен лимит откликов. Попробуйте через {minutes} мин.")

    # Валидация входных данных
    comment = validate_string_length(comment, MAX_COMMENT_LENGTH, "comment")

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO bids (
                order_id, worker_id, proposed_price, currency,
                comment, created_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """, (order_id, worker_id, proposed_price, currency, comment, now))

        conn.commit()
        bid_id = cursor.lastrowid
        logger.info(f"✅ Создан отклик: ID={bid_id}, Заказ={order_id}, Мастер={worker_id}, Цена={proposed_price} {currency}")
        return bid_id


def get_bids_for_order(order_id):
    """Получает все отклики для заказа с полной информацией о мастере"""
    with get_db_connection() as conn:

        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT
                b.*,
                w.name as worker_name,
                w.rating as worker_rating,
                w.rating_count as worker_rating_count,
                w.experience as worker_experience,
                w.phone as worker_phone,
                w.profile_photo as worker_profile_photo,
                w.portfolio_photos as worker_portfolio_photos,
                w.description as worker_description,
                w.city as worker_city,
                w.categories as worker_categories,
                w.verified_reviews as worker_verified_reviews,
                u.telegram_id as worker_telegram_id
            FROM bids b
            JOIN workers w ON b.worker_id = w.id
            JOIN users u ON w.user_id = u.id
            WHERE b.order_id = ?
            AND b.status = 'active'
            ORDER BY b.created_at ASC
        """, (order_id,))

        return cursor.fetchall()


def check_worker_bid_exists(order_id, worker_id):
    """Проверяет, откликался ли уже мастер на этот заказ"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT COUNT(*) FROM bids
            WHERE order_id = ? AND worker_id = ?
        """, (order_id, worker_id))

        return cursor.fetchone()[0] > 0


def get_bids_count_for_order(order_id):
    """Получает количество активных откликов для заказа"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT COUNT(*) FROM bids
            WHERE order_id = ? AND status = 'active'
        """, (order_id,))

        return cursor.fetchone()[0]


def get_bids_for_worker(worker_id):
    """
    Получает все отклики мастера с информацией о заказах.

    Args:
        worker_id: ID мастера в таблице workers

    Returns:
        Список откликов с информацией о заказе и клиенте
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT
                b.*,
                o.title as order_title,
                o.description as order_description,
                o.city as order_city,
                o.categories as order_categories,
                o.status as order_status,
                o.created_at as order_created_at,
                c.name as client_name,
                u.telegram_id as client_telegram_id
            FROM bids b
            JOIN orders o ON b.order_id = o.id
            JOIN clients c ON o.client_id = c.id
            JOIN users u ON c.user_id = u.id
            WHERE b.worker_id = ?
            ORDER BY b.created_at DESC
        """, (worker_id,))

        return cursor.fetchall()


def select_bid(bid_id):
    """
    ИСПРАВЛЕНО: Отмечает отклик как выбранный с защитой от race conditions.
    Проверяет что заказ еще не был выбран другим пользователем.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем order_id и проверяем статус заказа одним запросом
        cursor.execute("""
            SELECT b.order_id, o.status
            FROM bids b
            JOIN orders o ON b.order_id = o.id
            WHERE b.id = ?
        """, (bid_id,))
        result = cursor.fetchone()
        if not result:
            logger.warning(f"Отклик {bid_id} не найден")
            return False

        order_id, order_status = result[0], result[1]

        # ЗАЩИТА ОТ RACE CONDITION: проверяем что заказ еще не был выбран
        if order_status not in ('open', 'waiting_master_confirmation'):
            logger.warning(f"Заказ {order_id} уже в статусе '{order_status}', нельзя выбрать мастера")
            return False

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

        # Обновляем статус заказа ТОЛЬКО если он еще в open/waiting_master_confirmation
        # Это гарантирует что только один bid может быть выбран
        cursor.execute("""
            UPDATE orders
            SET status = 'master_selected'
            WHERE id = ? AND status IN ('open', 'waiting_master_confirmation')
        """, (order_id,))

        # Проверяем что UPDATE действительно произошел
        if cursor.rowcount == 0:
            logger.warning(f"Не удалось обновить заказ {order_id} - возможно race condition")
            conn.rollback()
            return False

        conn.commit()
        return True


def update_bid_status(bid_id, new_status):
    """Обновляет статус отклика (pending, selected, rejected)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE bids
            SET status = ?
            WHERE id = ?
        """, (new_status, bid_id))
        conn.commit()
        return cursor.rowcount > 0


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

    with get_db_connection() as conn:
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

    with get_db_connection() as conn:
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

