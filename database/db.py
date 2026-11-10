import aiosqlite
import datetime
from typing import Optional, Dict, Any, List
import config

async def init_db():
    """Initialize database tables."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                binance_api_key TEXT DEFAULT '',
                binance_api_secret TEXT DEFAULT '',
                is_active INTEGER DEFAULT 0,
                simulation_mode INTEGER DEFAULT 1,
                trade_mode TEXT DEFAULT 'spot',
                order_amount_usdt REAL DEFAULT 50.0,
                futures_leverage INTEGER DEFAULT 3,
                exit_strategy TEXT DEFAULT 'smart',
                tp_percent REAL DEFAULT 15.0,
                sl_percent REAL DEFAULT 5.0,
                trailing_stop_percent REAL DEFAULT 4.0,
                trailing_activation_percent REAL DEFAULT 8.0,
                max_hold_seconds INTEGER DEFAULT 90,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT,
                trade_mode TEXT,
                side TEXT DEFAULT 'BUY',
                order_id TEXT,
                buy_price REAL DEFAULT 0.0,
                quantity REAL DEFAULT 0.0,
                usdt_spent REAL DEFAULT 0.0,
                sell_price REAL DEFAULT 0.0,
                sell_order_id TEXT DEFAULT '',
                sell_time TIMESTAMP,
                pnl_percent REAL DEFAULT 0.0,
                pnl_usdt REAL DEFAULT 0.0,
                exit_reason TEXT DEFAULT '',
                status TEXT DEFAULT 'OPEN',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_title TEXT,
                source TEXT,
                parsed_coin TEXT,
                markets TEXT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve user settings by Telegram ID."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def create_or_update_user(telegram_id: int, username: str = "", first_name: str = "") -> Dict[str, Any]:
    """Ensure user exists in database."""
    user = await get_user(telegram_id)
    if not user:
        async with aiosqlite.connect(config.DATABASE_PATH) as db:
            await db.execute("""
                INSERT INTO users (telegram_id, username, first_name)
                VALUES (?, ?, ?)
            """, (telegram_id, username or "", first_name or ""))
            await db.commit()
        user = await get_user(telegram_id)
    return user

async def update_user_fields(telegram_id: int, **kwargs):
    """Update arbitrary user settings."""
    if not kwargs:
        return
    set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [telegram_id]
    query = f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?"
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(query, values)
        await db.commit()

async def get_active_traders() -> List[Dict[str, Any]]:
    """Retrieve all users who have the bot enabled (is_active = 1)."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE is_active = 1") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_all_users() -> List[Dict[str, Any]]:
    """Retrieve all registered users (for admin broadcasts)."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def record_listing(raw_title: str, source: str, parsed_coin: str, markets: str) -> int:
    """Record an announcement in the listings table."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO listings (raw_title, source, parsed_coin, markets)
            VALUES (?, ?, ?, ?)
        """, (raw_title, source, parsed_coin, markets))
        await db.commit()
        return cursor.lastrowid

async def record_trade(
    user_id: int,
    symbol: str,
    trade_mode: str,
    side: str,
    order_id: str,
    buy_price: float,
    quantity: float,
    usdt_spent: float,
    status: str = "OPEN"
) -> int:
    """Record a newly opened trade."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO trades (user_id, symbol, trade_mode, side, order_id, buy_price, quantity, usdt_spent, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, symbol, trade_mode, side, order_id, buy_price, quantity, usdt_spent, status))
        await db.commit()
        return cursor.lastrowid

async def close_trade(
    trade_id: int,
    sell_price: float,
    sell_order_id: str,
    pnl_percent: float,
    pnl_usdt: float,
    exit_reason: str,
    status: str = "CLOSED"
):
    """Update a trade upon completion/exit."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("""
            UPDATE trades
            SET sell_price = ?,
                sell_order_id = ?,
                sell_time = CURRENT_TIMESTAMP,
                pnl_percent = ?,
                pnl_usdt = ?,
                exit_reason = ?,
                status = ?
            WHERE id = ?
        """, (sell_price, sell_order_id, pnl_percent, pnl_usdt, exit_reason, status, trade_id))
        await db.commit()

async def get_user_trades(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent trades for a user."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM trades WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_recent_listings(limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve recent Upbit listing notices."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM listings ORDER BY id DESC LIMIT ?",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_open_trade_by_id(trade_id: int) -> Optional[Dict[str, Any]]:
    """Get trade details by ID."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

