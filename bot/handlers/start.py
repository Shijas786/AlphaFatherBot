from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import config
from database.db import create_or_update_user, get_user, update_user_fields, register_group
from database.encryption import decrypt_secret
from services.binance_service import binance_service
from bot.keyboards import get_main_dashboard_kb

async def format_dashboard_text(user: dict) -> str:
    telegram_id = user["telegram_id"]
    is_active = bool(user.get("is_active", 0))
    trade_mode = user.get("trade_mode", "spot").upper()
    order_amount = user.get("order_amount_usdt", 50.0)
    has_api = bool(user.get("binance_api_key"))

    status_icon = "🟢 ACTIVE (Auto-buying listings)" if is_active else "⚪ PAUSED"

    balance_text = "Disconnected"
    if has_api:
        try:
            api_key = decrypt_secret(user.get("binance_api_key", ""))
            api_secret = decrypt_secret(user.get("binance_api_secret", ""))
            bal = await binance_service.get_balance(api_key, api_secret, is_futures=(trade_mode == "FUTURES"))
            balance_text = f"${bal:,.2f} USDT"
        except Exception:
            balance_text = "API Key Error"

    text = (
        "THE CAPO TERMINAL ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ACCOUNT: `{telegram_id}`\n"
        f"STATUS: {status_icon}\n"
        f"MARKET: `{trade_mode}`\n"
        f"ORDER SIZE: `${order_amount:,.0f} USDT`\n"
        f"AVAILABLE USDT: `{balance_text}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "EXECUTION RULES:\n"
        f" • Take Profit: `+{user.get('tp_percent', 15):.0f}%` (Market Sell)\n"
        f" • Stop Loss: `-{user.get('sl_percent', 5):.0f}%` (Market Sell)\n"
        f" • Auto-Sell Timer: `{user.get('max_hold_seconds', 60)}s`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Tap 'OPEN PRO TERMINAL' below for the Web Dashboard."
    )
    return text

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command in private chats or groups."""
    chat = update.effective_chat
    user_obj = update.effective_user

    # If executed inside a group or supergroup
    if chat.type in ["group", "supergroup"]:
        await register_group(
            chat_id=chat.id,
            title=chat.title or "Telegram Group",
            chat_type=chat.type,
            added_by=user_obj.id if user_obj else None
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Open Capo Mini App", url=f"https://t.me/{config.TELEGRAM_BOT_USERNAME}/app")],
            [InlineKeyboardButton("🤖 Open Bot in Private", url=f"https://t.me/{config.TELEGRAM_BOT_USERNAME}?start=group")]
        ])
        group_text = (
            "⚡ *THE CAPO SNIPER // LISTING RADAR ACTIVE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏛 *Group:* `{chat.title}`\n"
            "✅ *Status:* Upbit Listing Alerts are **ENABLED**.\n\n"
            "📡 Every new Upbit listing notice (KRW / BTC / USDT) will be broadcasted here instantly within milliseconds via our proprietary Capo Radar stream.\n\n"
            "👉 *Want to snipe listings automatically with real money on Binance?*\n"
            "Tap below to open your personal Capo Terminal:"
        )
        await update.message.reply_text(group_text, reply_markup=kb, parse_mode="Markdown")
        return

    # Private chat dashboard
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

    # Safety check: if enabling, verify API key exists
    if new_state == 1 and not user.get("binance_api_key"):
        await query.answer("⚠️ Connect your Binance API Key first in Settings!", show_alert=True)
        return

    await update_user_fields(query.from_user.id, is_active=new_state)
    await query.answer(f"Sniping {'ACTIVATED! 🟢' if new_state else 'PAUSED ⚪'}")
    
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
        "1. *Instant Detection:* The bot listens 24/7 to Capo Ultra-Low Latency WebSocket & Upbit Direct API for new listing notices.\n"
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

