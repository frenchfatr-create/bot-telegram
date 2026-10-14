import aiosqlite
from typing import Optional, Dict, Any
from config import DATABASE_PATH


async def init_db() -> None:
    """Create tables and safely migrate existing databases."""
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
        cursor = await db.execute("PRAGMA table_info(submissions)")
        columns = [row[1] for row in await cursor.fetchall()]
        migrations = {
            "user_message_id": "ALTER TABLE submissions ADD COLUMN user_message_id INTEGER NOT NULL DEFAULT 0",
            "admin_message_id": "ALTER TABLE submissions ADD COLUMN admin_message_id INTEGER",
            "bot_id": "ALTER TABLE submissions ADD COLUMN bot_id INTEGER DEFAULT 0",
            "target_channels": "ALTER TABLE submissions ADD COLUMN target_channels TEXT DEFAULT ''",
            "status": "ALTER TABLE submissions ADD COLUMN status TEXT DEFAULT 'pending'",
            "moderator_name": "ALTER TABLE submissions ADD COLUMN moderator_name TEXT",
            "created_at": "ALTER TABLE submissions ADD COLUMN created_at TIMESTAMP",
        }
        for column, sql in migrations.items():
            if column not in columns:
                await db.execute(sql)
        await db.execute("UPDATE submissions SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                user_id INTEGER PRIMARY KEY,
                reason TEXT NOT NULL,
                banned_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_rate_limits (
                user_id INTEGER PRIMARY KEY,
                last_submission_at REAL NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bot_id INTEGER NOT NULL DEFAULT 0,
                appeal_text TEXT,
                status TEXT NOT NULL DEFAULT 'awaiting_text',
                admin_message_id INTEGER,
                moderator_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_submissions_admin_message ON submissions(bot_id, admin_message_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_appeals_user_status ON appeals(user_id, status)")
        await db.commit()


async def add_submission(user_id: int, user_message_id: int, bot_id: int = 0, target_channels: str = "") -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO submissions (user_id, user_message_id, bot_id, target_channels, status) VALUES (?, ?, ?, ?, 'pending')",
            (user_id, user_message_id, bot_id, target_channels))
        await db.commit()
        return int(cursor.lastrowid)


async def set_admin_message_id(sub_id: int, admin_message_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE submissions SET admin_message_id = ? WHERE id = ?", (admin_message_id, sub_id))
        await db.commit()


async def get_submission(sub_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_submission_by_admin_message(bot_id: int, admin_message_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM submissions WHERE bot_id = ? AND admin_message_id = ? ORDER BY id DESC LIMIT 1", (bot_id, admin_message_id)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_status(sub_id: int, status: str, moderator_name: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE submissions SET status = ?, moderator_name = ? WHERE id = ?", (status, moderator_name, sub_id))
        await db.commit()


async def get_ban(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bans WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def ban_user(user_id: int, reason: str, banned_by: Optional[int]) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""INSERT INTO bans (user_id, reason, banned_by) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason, banned_by=excluded.banned_by, created_at=CURRENT_TIMESTAMP""", (user_id, reason, banned_by))
        await db.commit()


async def unban_user(user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount > 0


async def check_and_mark_submission(user_id: int, now: float, interval: int = 60):
    """Atomic persistent rate limit: return (allowed, seconds_left)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute("SELECT last_submission_at FROM user_rate_limits WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row:
            remaining = interval - (now - float(row[0]))
            if remaining > 0:
                await db.commit()
                return False, max(1, int(remaining + 0.999))
        await db.execute("""INSERT INTO user_rate_limits (user_id, last_submission_at) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_submission_at=excluded.last_submission_at""", (user_id, now))
        await db.commit()
        return True, 0


async def create_appeal_draft(user_id: int, bot_id: int) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE appeals SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND status='awaiting_text'", (user_id,))
        cursor = await db.execute("INSERT INTO appeals (user_id, bot_id, status) VALUES (?, ?, 'awaiting_text')", (user_id, bot_id))
        await db.commit()
        return int(cursor.lastrowid)


async def get_awaiting_appeal(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM appeals WHERE user_id=? AND status='awaiting_text' ORDER BY id DESC LIMIT 1", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def submit_appeal(appeal_id: int, appeal_text: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE appeals SET appeal_text=?, status='pending', updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='awaiting_text'", (appeal_text, appeal_id))
        await db.commit()


async def set_appeal_admin_message_id(appeal_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE appeals SET admin_message_id=? WHERE id=?", (message_id, appeal_id))
        await db.commit()


async def get_appeal(appeal_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM appeals WHERE id=?", (appeal_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def resolve_appeal(appeal_id: int, status: str, moderator_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE appeals SET status=?, moderator_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, moderator_id, appeal_id))
        await db.commit()
