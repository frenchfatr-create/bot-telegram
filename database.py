import aiosqlite
from typing import Optional, Dict, Any
from config import DATABASE_PATH

async def init_db() -> None:
    """Создание таблиц базы данных и авто-миграция колонок."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_message_id INTEGER NOT NULL DEFAULT 0,
                admin_message_id INTEGER,
                bot_id INTEGER DEFAULT 0,
                target_channels TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                moderator_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Проверяем колонки на случай старых версий БД
        cursor = await db.execute("PRAGMA table_info(submissions)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "user_message_id" not in columns:
            await db.execute("ALTER TABLE submissions ADD COLUMN user_message_id INTEGER NOT NULL DEFAULT 0")
        if "admin_message_id" not in columns:
            await db.execute("ALTER TABLE submissions ADD COLUMN admin_message_id INTEGER")
        if "bot_id" not in columns:
            await db.execute("ALTER TABLE submissions ADD COLUMN bot_id INTEGER DEFAULT 0")
        if "target_channels" not in columns:
            await db.execute("ALTER TABLE submissions ADD COLUMN target_channels TEXT DEFAULT ''")
        await db.commit()

async def add_submission(user_id: int, user_message_id: int, bot_id: int = 0, target_channels: str = "") -> int:
    """Сохранить сообщение предложки."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO submissions (user_id, user_message_id, bot_id, target_channels, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (user_id, user_message_id, bot_id, target_channels)
        )
        await db.commit()
        return cursor.lastrowid

async def set_admin_message_id(sub_id: int, admin_message_id: int) -> None:
    """Сохранить ID сообщения в группе администраторов."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE submissions SET admin_message_id = ? WHERE id = ?",
            (admin_message_id, sub_id)
        )
        await db.commit()

async def get_submission(sub_id: int) -> Optional[Dict[str, Any]]:
    """Получить данные предложки по ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def update_status(sub_id: int, status: str, moderator_name: str) -> None:
    """Обновить статус решения (approved / rejected)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE submissions SET status = ?, moderator_name = ? WHERE id = ?",
            (status, moderator_name, sub_id)
        )
        await db.commit()
