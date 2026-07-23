import aiosqlite
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import json

DB_PATH = "assistant.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT DEFAULT 'Другое',
                description TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS capital (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                amount_usd REAL DEFAULT 0,
                amount_byn REAL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, name),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                UNIQUE(user_id, name),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS project_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                amount_usd REAL DEFAULT 0,
                amount_byn REAL DEFAULT 0,
                description TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                is_done INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                usd_byn_rate REAL DEFAULT 3.30,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
        await db.commit()


async def ensure_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()


# ========== EXPENSES ==========

async def add_expense(user_id: int, amount: float, category: str = "Другое", description: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO expenses (user_id, amount, category, description, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, description, datetime.now().isoformat())
        )
        await db.commit()


async def get_expenses(user_id: int, period: str = "month") -> List[Dict]:
    now = datetime.now()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif period == "week":
        start = (now - __import__("datetime").timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM expenses WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC",
            (user_id, start)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_expenses_total(user_id: int, period: str = "month") -> float:
    expenses = await get_expenses(user_id, period)
    return sum(e["amount"] for e in expenses)


# ========== CAPITAL ==========

async def set_capital(user_id: int, name: str, amount_usd: float = 0, amount_byn: float = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO capital (user_id, name, amount_usd, amount_byn, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, name) DO UPDATE SET
                amount_usd = excluded.amount_usd,
                amount_byn = excluded.amount_byn,
                updated_at = excluded.updated_at
        """, (user_id, name, amount_usd, amount_byn, datetime.now().isoformat()))
        await db.commit()


async def get_capital(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM capital WHERE user_id = ? ORDER BY name", (user_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_total_capital(user_id: int) -> Dict[str, float]:
    items = await get_capital(user_id)
    total_usd = sum(i["amount_usd"] for i in items)
    total_byn = sum(i["amount_byn"] for i in items)
    return {"usd": total_usd, "byn": total_byn}


# ========== PROJECTS ==========

async def get_or_create_project(user_id: int, name: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM projects WHERE user_id = ? AND name = ?", (user_id, name)
        )
        row = await cursor.fetchone()
        if row:
            return row[0]
        cursor = await db.execute(
            "INSERT INTO projects (user_id, name) VALUES (?, ?)", (user_id, name)
        )
        await db.commit()
        return cursor.lastrowid


async def add_project_transaction(user_id: int, project_name: str, amount_usd: float = 0, amount_byn: float = 0, description: str = ""):
    project_id = await get_or_create_project(user_id, project_name)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO project_transactions (user_id, project_id, amount_usd, amount_byn, description, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, project_id, amount_usd, amount_byn, description, datetime.now().isoformat())
        )
        await db.commit()


async def get_project_profit(user_id: int, project_name: str, period: str = "month") -> Dict[str, float]:
    now = datetime.now()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif period == "week":
        start = (now - __import__("datetime").timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT SUM(pt.amount_usd) as usd, SUM(pt.amount_byn) as byn
            FROM project_transactions pt
            JOIN projects p ON p.id = pt.project_id
            WHERE pt.user_id = ? AND p.name = ? AND pt.created_at >= ?
        """, (user_id, project_name, start))
        row = await cursor.fetchone()
        return {"usd": row["usd"] or 0, "byn": row["byn"] or 0}


async def get_all_projects_profit(user_id: int, period: str = "month") -> Dict[str, float]:
    now = datetime.now()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif period == "week":
        start = (now - __import__("datetime").timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT SUM(amount_usd) as usd, SUM(amount_byn) as byn
            FROM project_transactions
            WHERE user_id = ? AND created_at >= ?
        """, (user_id, start))
        row = await cursor.fetchone()
        return {"usd": row["usd"] or 0, "byn": row["byn"] or 0}


async def get_projects_list(user_id: int) -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name FROM projects WHERE user_id = ? ORDER BY name", (user_id,)
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


# ========== NOTES ==========

async def add_note(user_id: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO notes (user_id, text, created_at) VALUES (?, ?, ?)",
            (user_id, text, datetime.now().isoformat())
        )
        await db.commit()


async def get_notes(user_id: int, limit: int = 50) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM notes WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ========== REMINDERS ==========

async def add_reminder(user_id: int, text: str, remind_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reminders (user_id, text, remind_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, text, remind_at, datetime.now().isoformat())
        )
        await db.commit()


async def get_active_reminders(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM reminders WHERE user_id = ? AND is_done = 0 ORDER BY remind_at",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ========== SETTINGS ==========

async def get_rate(user_id: int) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT usd_byn_rate FROM settings WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 3.30


async def set_rate(user_id: int, rate: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE settings SET usd_byn_rate = ? WHERE user_id = ?", (rate, user_id)
        )
        await db.commit()
