from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from database.db import get_user, get_user_trades
from services.position_tracker import position_tracker

async def view_trades_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display user's recent trades and performance."""
    query = update.callback_query
    await query.answer()

    trades = await get_user_trades(query.from_user.id, limit=8)
    if not trades:
        text = "📊 *TRADE HISTORY*\n━━━━━━━━━━━━━━━━━━━━━━\nNo trades recorded yet. Waiting for Upbit listings!"
    else:
        text = "📊 *RECENT TRADE HISTORY*\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for t in trades:
            status = t["status"]
            symbol = t["symbol"]
            mode = t["trade_mode"].upper()
            spent = t["usdt_spent"]
            pnl_pct = t.get("pnl_percent", 0.0)
            pnl_usdt = t.get("pnl_usdt", 0.0)
            reason = t.get("exit_reason", "")

            pnl_str = f"+${pnl_usdt:.2f} (+{pnl_pct:.1f}%)" if pnl_pct >= 0 else f"-${abs(pnl_usdt):.2f} ({pnl_pct:.1f}%)"
            icon = "🟢" if pnl_pct >= 0 else "🔴"

            text += (
                f"{icon} *{symbol}* ({mode})\n"
                f"   • Size: `${spent:.0f}` | Result: `{pnl_str}`\n"
                f"   • Status: `{status}` | Exit: `{reason}`\n\n"
            )

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="refresh_dashboard")]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def panic_sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Emergency Panic Sell 1-click execution."""
    query = update.callback_query
    trade_id = int(query.data.replace("panic_sell_", ""))

    user = await get_user(query.from_user.id)
    if not user:
        await query.answer("User profile not found.", show_alert=True)
        return

    await query.answer("🚨 Executing Panic Sell...")

    res = await position_tracker.panic_sell_manual(trade_id, user)
    if res.get("success"):
        pnl = res.get("pnl_percent", 0.0)
        pnl_usdt = res.get("pnl_usdt", 0.0)
        pnl_str = f"+${pnl_usdt:.2f} (+{pnl:.2f}%)" if pnl >= 0 else f"-${abs(pnl_usdt):.2f} ({pnl:.2f}%)"
        await query.edit_message_text(
            f"✅ *PANIC SELL EXECUTED!*\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Trade #{trade_id} closed at market.\n"
            f"Realized PnL: `{pnl_str}`",
            parse_mode="Markdown"
        )
    else:
        err = res.get("error", "Unknown error")
        await query.message.reply_text(f"⚠️ Panic sell could not be executed: {err}")

