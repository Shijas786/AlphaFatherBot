import logging
from typing import Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ChatMemberHandler,
    ContextTypes,
    filters
)
import config
from database.db import register_group, deactivate_group, get_active_groups
from bot.handlers.start import (
    start_command,
    refresh_dashboard_callback,
    toggle_active_callback,
    toggle_trade_mode_callback,
    view_help_callback
)
from bot.handlers.settings import (
    open_settings_callback,
    set_amount_menu_callback,
    set_amount_val_callback,
    set_tp_menu_callback,
    set_tp_val_callback,
    set_sl_menu_callback,
    set_sl_val_callback,
    set_timeout_menu_callback,
    set_timeout_val_callback,
    set_leverage_menu_callback,
    set_leverage_val_callback
)
from bot.handlers.api_keys import (
    start_api_setup,
    receive_api_key,
    receive_api_secret,
    cancel_api_setup,
    STATE_WAITING_API_KEY,
    STATE_WAITING_API_SECRET
)
from bot.handlers.trades import (
    view_trades_callback,
    panic_sell_callback
)
from bot.handlers.admin import (
    admin_simulate_listing_command,
    admin_broadcast_command,
    admin_stats_command
)
from bot.keyboards import get_panic_sell_kb

logger = logging.getLogger(__name__)

async def track_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bot added to or removed from groups/supergroups."""
    result = update.my_chat_member
    if not result:
        return

    chat = update.effective_chat
    user = update.effective_user
    new_status = result.new_chat_member.status

    # Bot added to group or promoted to admin
    if new_status in ["member", "administrator"]:
        await register_group(
            chat_id=chat.id,
            title=chat.title or "Telegram Group",
            chat_type=chat.type,
            added_by=user.id if user else None
        )
        logger.info(f"⚡ Bot joined group {chat.id} ({chat.title}). Alerts enabled!")
        try:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Open Capo Mini App", url=f"https://t.me/{config.TELEGRAM_BOT_USERNAME}/app")]
            ])
            import html
            safe_title = html.escape(chat.title or "Telegram Group")
            welcome_text = (
                "⚡ <b>THE CAPO SNIPER // LISTING RADAR ACTIVATED</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏛 <b>Group:</b> <code>{safe_title}</code>\n"
                "✅ <b>Status:</b> Upbit Listing Announcements are now <b>LIVE</b>.\n\n"
                "📡 Every new listing announced by Upbit (KRW / BTC / USDT) will be pushed into this group within milliseconds via our proprietary ultra-low latency WebSocket stream.\n\n"
                "👉 <b>Want to snipe listings automatically with real money on Binance?</b>\n"
                "Tap below to open your personal Capo Terminal:"
            )
            await context.bot.send_message(
                chat_id=chat.id,
                text=welcome_text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Could not send welcome message to group {chat.id}: {e}")

    # Bot kicked or left
    elif new_status in ["left", "kicked"]:
        await deactivate_group(chat.id)
        logger.info(f"Bot left/kicked from group {chat.id} ({chat.title}). Alerts deactivated.")

async def group_auto_register_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Passive group observer: auto-register any group where bot sees any message or interaction."""
    chat = update.effective_chat
    if chat and chat.type in ["group", "supergroup"]:
        user = update.effective_user
        await register_group(
            chat_id=chat.id,
            title=chat.title or "Telegram Group",
            chat_type=chat.type,
            added_by=user.id if user else None
        )

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts command in groups or private chats."""
    chat = update.effective_chat
    user = update.effective_user
    if chat.type in ["group", "supergroup"]:
        await register_group(
            chat_id=chat.id,
            title=chat.title or "Telegram Group",
            chat_type=chat.type,
            added_by=user.id if user else None
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Open Capo Mini App", url=f"https://t.me/{config.TELEGRAM_BOT_USERNAME}/app")]
        ])
        import html
        safe_title = html.escape(chat.title or "Telegram Group")
        text = (
            "⚡ <b>THE CAPO SNIPER // RADAR STATUS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏛 <b>Group:</b> <code>{safe_title}</code>\n"
            "🟢 <b>Status:</b> Upbit Listing Alerts are <b>ACTIVE</b>\n\n"
            "📡 Every new Upbit listing notice (KRW / BTC / USDT) will be broadcasted here instantly within milliseconds via our ultra-low latency WebSocket feed.\n\n"
            "👉 <b>Want to trade automatically on Binance?</b> Tap below:"
        )
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await start_command(update, context)

async def test_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a test listing alert to verify group delivery: /test_alert [COIN]"""
    chat = update.effective_chat
    user = update.effective_user
    coin = context.args[0].upper() if (context.args and len(context.args) > 0) else "BTC"

    if chat.type in ["group", "supergroup"]:
        await register_group(
            chat_id=chat.id,
            title=chat.title or "Telegram Group",
            chat_type=chat.type,
            added_by=user.id if user else None
        )

    notifier = TelegramNotifier(context.bot)
    await update.message.reply_text(f"🧪 <i>Firing test Upbit listing alert for <b>${coin}</b>...</i>", parse_mode="HTML")
    await notifier.broadcast_listing_to_groups(
        coin=coin,
        binance_symbol=f"{coin}USDT",
        raw_title=f"[거래] KRW, BTC, USDT 마켓 디지털 자산 추가 안내 ({coin})",
        source="CapoTestFeed",
        latency_ms=15
    )

def build_telegram_app() -> Application:
    """Build and configure the Telegram application."""
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env!")

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Chat Member handler for Groups (triggers when bot is added/removed)
    app.add_handler(ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Passive group observer: auto-register any group when a message/activity occurs
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, group_auto_register_message), group=99)

    # Conversation handler for API keys setup
    api_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_api_setup, pattern="^setup_api_keys$")],
        states={
            STATE_WAITING_API_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_key)
            ],
            STATE_WAITING_API_SECRET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_secret)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_api_setup),
            CallbackQueryHandler(cancel_api_setup, pattern="^cancel_api_setup$")
        ],
        per_message=False
    )
    app.add_handler(api_conv_handler)

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("test_alert", test_alert_command))
    app.add_handler(CommandHandler("simulate_listing", admin_simulate_listing_command))
    app.add_handler(CommandHandler("broadcast", admin_broadcast_command))
    app.add_handler(CommandHandler("stats", admin_stats_command))

    # Callback Query handlers - Dashboard
    app.add_handler(CallbackQueryHandler(refresh_dashboard_callback, pattern="^refresh_dashboard$"))
    app.add_handler(CallbackQueryHandler(toggle_active_callback, pattern="^toggle_active$"))
    app.add_handler(CallbackQueryHandler(toggle_trade_mode_callback, pattern="^toggle_trade_mode$"))
    app.add_handler(CallbackQueryHandler(view_help_callback, pattern="^view_help$"))
    app.add_handler(CallbackQueryHandler(view_trades_callback, pattern="^view_trades$"))

    # Settings callbacks
    app.add_handler(CallbackQueryHandler(open_settings_callback, pattern="^open_settings$"))
    app.add_handler(CallbackQueryHandler(set_amount_menu_callback, pattern="^set_amount_menu$"))
    app.add_handler(CallbackQueryHandler(set_amount_val_callback, pattern="^set_amt_"))
    app.add_handler(CallbackQueryHandler(set_tp_menu_callback, pattern="^set_tp_menu$"))
    app.add_handler(CallbackQueryHandler(set_tp_val_callback, pattern="^set_tp_"))
    app.add_handler(CallbackQueryHandler(set_sl_menu_callback, pattern="^set_sl_menu$"))
    app.add_handler(CallbackQueryHandler(set_sl_val_callback, pattern="^set_sl_"))
    app.add_handler(CallbackQueryHandler(set_timeout_menu_callback, pattern="^set_timeout_menu$"))
    app.add_handler(CallbackQueryHandler(set_timeout_val_callback, pattern="^set_to_"))
    app.add_handler(CallbackQueryHandler(set_leverage_menu_callback, pattern="^set_leverage_menu$"))
    app.add_handler(CallbackQueryHandler(set_leverage_val_callback, pattern="^set_lev_"))

    # Emergency Panic Sell callback
    app.add_handler(CallbackQueryHandler(panic_sell_callback, pattern="^panic_sell_"))

    return app

class TelegramNotifier:
    def __init__(self, bot):
        self.bot = bot

    async def notify_buy(self, user_id: int, data: dict):
        """Notify user that a listing order was executed."""
        if data.get("failed"):
            text = (
                f"⚠️ *ORDER EXECUTION FAILED*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 *Symbol:* `{data['symbol']}`\n"
                f"⏱ *Detection Latency:* `{data.get('latency_ms', 0)}ms`\n"
                f"❌ *Error:* `{data.get('error', 'Unknown')}`"
            )
            try:
                await self.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to send buy fail notification: {e}")
            return

        trade_id = data["trade_id"]
        symbol = data["symbol"]
        price = data["buy_price"]
        amount = data["usdt_spent"]
        mode = data["trade_mode"].upper()
        latency = data.get("latency_ms", 0)
        is_sim = data.get("is_simulation", False)

        tag = "🧪 [SIMULATED] " if is_sim else "💰 [REAL ORDER] "

        text = (
            f"⚡ *{tag}UPBIT LISTING SNIPED!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Token:* `#{symbol}`\n"
            f"🏦 *Market:* `{mode}`\n"
            f"💵 *Fill Price:* `${price:.6f}`\n"
            f"📦 *Position Size:* `${amount:.2f} USDT`\n"
            f"⏱ *Total Latency:* `{latency}ms`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Smart Exit Engine active:* Watching trailing peak, TP & SL...\n"
            f"Or click below to panic exit immediately:"
        )

        kb = get_panic_sell_kb(trade_id)
        try:
            await self.bot.send_message(chat_id=user_id, text=text, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send buy notification: {e}")

    async def notify_exit(self, user_id: int, data: dict):
        """Notify user that trade exit executed."""
        symbol = data["symbol"]
        entry = data["buy_price"]
        exit_p = data["sell_price"]
        pnl_pct = data["pnl_percent"]
        pnl_usdt = data["pnl_usdt"]
        reason = data["exit_reason"]
        is_sim = data.get("is_simulation", False)

        tag = "🧪 [SIMULATED] " if is_sim else "💰 [REAL TRADE] "
        icon = "🎉" if pnl_pct >= 0 else "🛑"
        sign = "+" if pnl_pct >= 0 else ""

        text = (
            f"{icon} *{tag}POSITION CLOSED!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Token:* `#{symbol}`\n"
            f"📈 *Entry:* `${entry:.6f}`  ➡️  *Exit:* `${exit_p:.6f}`\n"
            f"💵 *PnL:* `{sign}${pnl_usdt:.2f} ({sign}{pnl_pct:.2f}%)`\n"
            f"📌 *Exit Reason:* `{reason}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            await self.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send exit notification: {e}")

    async def broadcast_listing_to_groups(
        self,
        coin: str,
        binance_symbol: Optional[str],
        raw_title: str,
        source: str,
        latency_ms: int = 0
    ):
        """Broadcast new Upbit listing notice to all registered Telegram groups."""
        groups = await get_active_groups()
        if not groups:
            logger.info("No registered groups to broadcast listing alert.")
            return

        logger.info(f"📢 Broadcasting Upbit listing for '{coin}' to {len(groups)} group(s)...")

        import html
        safe_coin = html.escape(str(coin))
        safe_title = html.escape(str(raw_title))

        if binance_symbol:
            safe_symbol = html.escape(str(binance_symbol))
            binance_line = f"🟢 <b>Binance:</b> Tradable as <code>#{safe_symbol}</code>"
            btn_text = f"⚡ Snipe #{safe_symbol} on Capo"
        else:
            binance_line = "⚪ <b>Binance:</b> Asset not currently listed on Binance USDT"
            btn_text = "⚡ Open Capo Terminal"

        app_url = f"https://t.me/{config.TELEGRAM_BOT_USERNAME}/app"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(btn_text, url=app_url)]
        ])

        feed_label = "Capo Core WebSocket" if ("Tree" in str(source) or "CapoStream" in str(source)) else "Capo Direct Feed"
        html_text = (
            "🚨 <b>NEW UPBIT LISTING ANNOUNCEMENT!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>Token:</b> <code>${safe_coin}</code>\n"
            f"{binance_line}\n"
            f"⏱ <b>Detection Latency:</b> <code>{latency_ms}ms</code> ({feed_label})\n"
            f"📰 <b>Headline:</b>\n<i>{safe_title}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>The Capo Sniper Engine:</b> Sub-second listing execution on Binance Spot & Futures."
        )

        for g in groups:
            chat_id = g["chat_id"]
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=html_text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to send HTML listing alert to group {chat_id}: {e}. Retrying plain text...")
                try:
                    plain_text = (
                        f"🚨 NEW UPBIT LISTING ANNOUNCEMENT!\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Token: ${coin}\n"
                        f"{'Binance: #' + binance_symbol if binance_symbol else 'Binance: Asset not on Binance USDT'}\n"
                        f"Detection Latency: {latency_ms}ms ({feed_label})\n"
                        f"Headline: {raw_title}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"The Capo Sniper Engine: https://t.me/{config.TELEGRAM_BOT_USERNAME}/app"
                    )
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=plain_text,
                        reply_markup=kb
                    )
                except Exception as e2:
                    err_str = str(e2).lower()
                    logger.error(f"Failed plain text fallback for group {chat_id}: {e2}")
                    if "forbidden" in err_str or "kicked" in err_str or "chat not found" in err_str:
                        await deactivate_group(chat_id)

