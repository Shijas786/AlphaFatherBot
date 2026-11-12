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
                trade_mode TEXT DEFAULT 'spot',
                order_amount_usdt REAL DEFAULT 50.0,
                futures_leverage INTEGER DEFAULT 3,
                tp_percent REAL DEFAULT 15.0,
                sl_percent REAL DEFAULT 5.0,
                max_hold_seconds INTEGER DEFAULT 60,
                profit_share_percent REAL DEFAULT 10.0,
                total_profit_usdt REAL DEFAULT 0.0,
                total_fees_due_usdt REAL DEFAULT 0.0,
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
                fee_rate REAL DEFAULT 0.10,
                fee_usdt REAL DEFAULT 0.0,
                fee_status TEXT DEFAULT 'CALCULATED',
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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS telegram_groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                chat_type TEXT,
                is_active INTEGER DEFAULT 1,
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seamless migrations for existing databases
        migrations = [
            "ALTER TABLE users ADD COLUMN profit_share_percent REAL DEFAULT 10.0",
            "ALTER TABLE users ADD COLUMN total_profit_usdt REAL DEFAULT 0.0",
            "ALTER TABLE users ADD COLUMN total_fees_due_usdt REAL DEFAULT 0.0",
            "ALTER TABLE trades ADD COLUMN fee_rate REAL DEFAULT 0.10",
            "ALTER TABLE trades ADD COLUMN fee_usdt REAL DEFAULT 0.0",
            "ALTER TABLE trades ADD COLUMN fee_status TEXT DEFAULT 'CALCULATED'"
        ]
        for m in migrations:
            try:
                await db.execute(m)
            except Exception:
                pass

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
    """Update a trade upon completion/exit and calculate profit sharing."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Fetch trade user_id
        user_id = None
        async with db.execute("SELECT user_id FROM trades WHERE id = ?", (trade_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                user_id = row["user_id"]

        fee_rate = 0.10
        fee_usdt = 0.0

        if user_id:
            async with db.execute("SELECT profit_share_percent FROM users WHERE telegram_id = ?", (user_id,)) as cursor:
                u_row = await cursor.fetchone()
                if u_row and u_row["profit_share_percent"]:
                    fee_rate = float(u_row["profit_share_percent"]) / 100.0

            # Calculate profit sharing on winning trades only
            if pnl_usdt > 0:
                fee_usdt = round(pnl_usdt * fee_rate, 4)
                # Update user running ledger totals
                await db.execute("""
                    UPDATE users
                    SET total_profit_usdt = total_profit_usdt + ?,
                        total_fees_due_usdt = total_fees_due_usdt + ?
                    WHERE telegram_id = ?
                """, (pnl_usdt, fee_usdt, user_id))

        await db.execute("""
            UPDATE trades
            SET sell_price = ?,
                sell_order_id = ?,
                sell_time = CURRENT_TIMESTAMP,
                pnl_percent = ?,
                pnl_usdt = ?,
                fee_rate = ?,
                fee_usdt = ?,
                fee_status = 'CALCULATED',
                exit_reason = ?,
                status = ?
            WHERE id = ?
        """, (sell_price, sell_order_id, pnl_percent, pnl_usdt, fee_rate, fee_usdt, exit_reason, status, trade_id))
        await db.commit()

async def get_user_profit_stats(user_id: int) -> Dict[str, Any]:
    """Calculate aggregate trade metrics and profit sharing for a user."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) as winning_trades,
                COALESCE(SUM(pnl_usdt), 0.0) as gross_pnl_usdt,
                COALESCE(SUM(fee_usdt), 0.0) as total_fee_usdt,
                COALESCE(SUM(usdt_spent), 0.0) as total_volume_usdt
            FROM trades
            WHERE user_id = ? AND status = 'CLOSED'
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            total_trades = row["total_trades"] or 0
            wins = row["winning_trades"] or 0
            gross_pnl = round(float(row["gross_pnl_usdt"]), 2)
            fees = round(float(row["total_fee_usdt"]), 2)
            net_profit = round(gross_pnl - fees, 2)
            win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0.0

            return {
                "total_trades": total_trades,
                "win_rate": win_rate,
                "gross_pnl_usdt": gross_pnl,
                "platform_fee_accrued_usdt": fees,
                "net_user_profit_usdt": net_profit,
                "total_volume_usdt": round(float(row["total_volume_usdt"]), 2)
            }

async def get_global_profit_sharing_summary() -> Dict[str, Any]:
    """Retrieve global platform-wide stats for admin dashboard."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT 
                COUNT(DISTINCT user_id) as active_traders_count,
                COUNT(*) as total_trades,
                COALESCE(SUM(pnl_usdt), 0.0) as total_user_profits,
                COALESCE(SUM(fee_usdt), 0.0) as total_fees_accrued,
                COALESCE(SUM(usdt_spent), 0.0) as total_volume
            FROM trades
            WHERE status = 'CLOSED'
        """) as cursor:
            stats = await cursor.fetchone()

        async with db.execute("""
            SELECT 
                u.telegram_id, u.username, u.first_name,
                COUNT(t.id) as trades_count,
                COALESCE(SUM(t.pnl_usdt), 0.0) as total_pnl,
                COALESCE(SUM(t.fee_usdt), 0.0) as total_fees
            FROM users u
            LEFT JOIN trades t ON u.telegram_id = t.user_id AND t.status = 'CLOSED'
            GROUP BY u.telegram_id
            HAVING total_pnl > 0
            ORDER BY total_pnl DESC
            LIMIT 10
        """) as cursor:
            top_users = await cursor.fetchall()

        return {
            "total_trades": stats["total_trades"] or 0,
            "total_user_profits": round(float(stats["total_user_profits"]), 2),
            "total_fees_accrued": round(float(stats["total_fees_accrued"]), 2),
            "total_volume": round(float(stats["total_volume"]), 2),
            "top_earning_users": [dict(r) for r in top_users]
        }

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

# ================= Telegram Groups Alert Management =================
async def register_group(chat_id: int, title: str = "", chat_type: str = "group", added_by: Optional[int] = None):
    """Register or re-activate a Telegram group for listing broadcasts."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO telegram_groups (chat_id, title, chat_type, is_active, added_by, updated_at)
            VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                chat_type = excluded.chat_type,
                is_active = 1,
                added_by = COALESCE(excluded.added_by, telegram_groups.added_by),
                updated_at = CURRENT_TIMESTAMP
        """, (chat_id, title or "Telegram Group", chat_type, added_by))
        await db.commit()

async def deactivate_group(chat_id: int):
    """Mark a group as inactive (e.g. when bot is removed/kicked)."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("""
            UPDATE telegram_groups SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = ?
        """, (chat_id,))
        await db.commit()

async def get_active_groups() -> List[Dict[str, Any]]:
    """Retrieve all active groups registered for listing alerts."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT chat_id, title, chat_type FROM telegram_groups WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_group_stats() -> Dict[str, int]:
    """Retrieve group count metrics."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM telegram_groups WHERE is_active = 1") as c1:
            active = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM telegram_groups") as c2:
            total = (await c2.fetchone())[0]
        return {"active_groups": active, "total_groups": total}

