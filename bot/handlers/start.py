from telegram import Update
from telegram.ext import ContextTypes
from database.db import create_or_update_user, get_user, update_user_fields
from database.encryption import decrypt_secret
from services.binance_service import binance_service
from bot.keyboards import get_main_dashboard_kb

async def format_dashboard_text(user: dict) -> str:
    telegram_id = user["telegram_id"]
    is_active = bool(user.get("is_active", 0))
    is_sim = bool(user.get("simulation_mode", 1))
    trade_mode = user.get("trade_mode", "spot").upper()
    order_amount = user.get("order_amount_usdt", 50.0)
    has_api = bool(user.get("binance_api_key"))

    status_icon = "🟢 ACTIVE (Sniping listings)" if is_active else "🔴 PAUSED"
    mode_icon = "🧪 SIMULATION (Paper Trading - No Real Risk)" if is_sim else "💰 REAL MONEY (Live Trading)"

    balance_text = "N/A (Simulation Mode)"
    if has_api and not is_sim:
        try:
            api_key = decrypt_secret(user.get("binance_api_key", ""))
            api_secret = decrypt_secret(user.get("binance_api_secret", ""))
            bal = await binance_service.get_balance(api_key, api_secret, is_futures=(trade_mode == "FUTURES"))
            balance_text = f"${bal:.2f} USDT"
        except Exception:
            balance_text = "API Key Error"

    text = (
        "⚡ *UPBIT LISTING SNIPER BOT*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Account:* `{telegram_id}`\n"
        f"📡 *Status:* {status_icon}\n"
        f"⚙️ *Mode:* {mode_icon}\n"
        f"🏦 *Market:* `{trade_mode}`\n"
        f"💵 *Order Size:* `${order_amount:.0f} USDT`\n"
        f"💼 *Binance Balance:* `{balance_text}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 *Smart Exit Rules:*\n"
        f" • *Take Profit:* `+{user.get('tp_percent', 15):.0f}%`\n"
        f" • *Stop Loss:* `-{user.get('sl_percent', 5):.0f}%`\n"
        f" • *Trailing Pullback:* `{user.get('trailing_stop_percent', 4):.0f}%` (arms at +{user.get('trailing_activation_percent', 8):.0f}%)\n"
        f" • *Max Hold Duration:* `{user.get('max_hold_seconds', 90)}s`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Tip:* Test with Simulation Mode first to observe speed and PnL!"
    )
    return text

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_obj = update.effective_user
    user = await create_or_update_user(
        telegram_id=user_obj.id,
        username=user_obj.username or "",
        first_name=user_obj.first_name or ""
    )
    text = await format_dashboard_text(user)
    reply_markup = get_main_dashboard_kb(user)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def refresh_dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback to refresh dashboard view."""
    query = update.callback_query
    await query.answer("Dashboard updated!")
    user = await get_user(query.from_user.id)
    if not user:
        return
    text = await format_dashboard_text(user)
    reply_markup = get_main_dashboard_kb(user)
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception:
        pass

async def toggle_active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle bot ON/OFF."""
    query = update.callback_query
    user = await get_user(query.from_user.id)
    if not user:
        return

    current_state = bool(user.get("is_active", 0))
    new_state = 0 if current_state else 1

    # Safety check: if enabling in real mode, verify API key
    if new_state == 1 and not user.get("simulation_mode", 1) and not user.get("binance_api_key"):
        await query.answer("⚠️ Please connect your Binance API Key first, or switch to Simulation Mode!", show_alert=True)
        return

    await update_user_fields(query.from_user.id, is_active=new_state)
    await query.answer(f"Bot {'ACTIVATED! 🟢' if new_state else 'PAUSED 🔴'}")
    
    updated_user = await get_user(query.from_user.id)
    text = await format_dashboard_text(updated_user)
    await query.edit_message_text(text, reply_markup=get_main_dashboard_kb(updated_user), parse_mode="Markdown")

async def toggle_sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle between Paper Simulation and Real Trading."""
    query = update.callback_query
    user = await get_user(query.from_user.id)
    if not user:
        return

    current_sim = bool(user.get("simulation_mode", 1))
    new_sim = 0 if current_sim else 1

    await update_user_fields(query.from_user.id, simulation_mode=new_sim)
    await query.answer(f"Mode switched to {'🧪 SIMULATION' if new_sim else '💰 REAL FUNDS'}")

    updated_user = await get_user(query.from_user.id)
    text = await format_dashboard_text(updated_user)
    await query.edit_message_text(text, reply_markup=get_main_dashboard_kb(updated_user), parse_mode="Markdown")

async def toggle_trade_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle between Spot and Futures."""
    query = update.callback_query
    user = await get_user(query.from_user.id)
    if not user:
        return

    current_mode = user.get("trade_mode", "spot")
    new_mode = "futures" if current_mode == "spot" else "spot"

    await update_user_fields(query.from_user.id, trade_mode=new_mode)
    await query.answer(f"Switched market to {new_mode.upper()}")

    updated_user = await get_user(query.from_user.id)
    text = await format_dashboard_text(updated_user)
    await query.edit_message_text(text, reply_markup=get_main_dashboard_kb(updated_user), parse_mode="Markdown")

async def view_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help documentation."""
    query = update.callback_query
    await query.answer()
    help_text = (
        "📖 *HOW THE BOT WORKS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1. *Instant Detection:* The bot listens 24/7 to Tree News WebSocket & Upbit Official Notice API for new listing notices.\n"
        "2. *Zero-Latency Parsing:* When a notice appears (e.g. `KRW 마켓 추가 (XYZ)`), the ticker `XYZ` is parsed in milliseconds.\n"
        "3. *Parallel Binance Order:* The bot checks if `XYZUSDT` exists on Binance and fires Market Buy orders simultaneously for all active users.\n"
        "4. *Smart Exit:* The position tracker watches real-time prices:\n"
        "   • Hits Take Profit (e.g. +15%)\n"
        "   • Trails the pump peak and sells if it drops 4%\n"
        "   • Stops loss if trade moves against you (-5%)\n"
        "   • Auto-exits after 90 seconds if pump fades.\n"
        "   • Or click *PANIC SELL* anytime in Telegram!\n\n"
        "🔒 *Security:* Your Binance Secret Key is encrypted using military-grade AES-256-GCM. We never require or accept withdrawal permissions."
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="refresh_dashboard")]])
    await query.edit_message_text(help_text, reply_markup=kb, parse_mode="Markdown")

