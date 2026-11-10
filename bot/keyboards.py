from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from typing import Dict, Any
import config

def get_main_dashboard_kb(user: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Main Control Dashboard Keyboard."""
    is_active = bool(user.get("is_active", 0))
    is_sim = bool(user.get("simulation_mode", 1))
    trade_mode = user.get("trade_mode", "spot").upper()
    has_api = bool(user.get("binance_api_key"))

    status_text = "🟢 Status: ACTIVE" if is_active else "🔴 Status: PAUSED"
    toggle_data = "toggle_active"

    sim_text = "🧪 Mode: SIMULATION (Paper)" if is_sim else "💰 Mode: REAL FUNDS"
    sim_data = "toggle_sim"

    api_text = "🔑 Binance API: Connected ✅" if has_api else "🔑 Connect Binance API ⚠️"

    keyboard = []

    # If WEBAPP_URL is configured, add top Launch Mini App button
    if config.WEBAPP_URL:
        keyboard.append([
            InlineKeyboardButton("🚀 Open Sniper Mini App", web_app=WebAppInfo(url=config.WEBAPP_URL))
        ])

    keyboard.extend([
        [
            InlineKeyboardButton(status_text, callback_data=toggle_data),
            InlineKeyboardButton(sim_text, callback_data=sim_data)
        ],
        [
            InlineKeyboardButton(f"📈 Market: {trade_mode}", callback_data="toggle_trade_mode"),
            InlineKeyboardButton(f"💵 Size: ${user.get('order_amount_usdt', 50):.0f}", callback_data="open_settings")
        ],
        [
            InlineKeyboardButton(api_text, callback_data="setup_api_keys")
        ],
        [
            InlineKeyboardButton("⚙️ Strategy Settings", callback_data="open_settings"),
            InlineKeyboardButton("📊 Trade History", callback_data="view_trades")
        ],
        [
            InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="refresh_dashboard"),
            InlineKeyboardButton("ℹ️ Help", callback_data="view_help")
        ]
    ])
    return InlineKeyboardMarkup(keyboard)

def get_settings_kb(user: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Trading Settings Keyboard."""
    trade_mode = user.get("trade_mode", "spot")
    leverage = user.get("futures_leverage", 3)
    order_amount = user.get("order_amount_usdt", 50.0)
    tp = user.get("tp_percent", 15.0)
    sl = user.get("sl_percent", 5.0)
    trailing_pct = user.get("trailing_stop_percent", 4.0)
    max_hold = user.get("max_hold_seconds", 90)

    keyboard = [
        [
            InlineKeyboardButton(f"💵 Order Size: ${order_amount:.0f}", callback_data="set_amount_menu")
        ],
        [
            InlineKeyboardButton(f"🎯 Take Profit: +{tp:.0f}%", callback_data="set_tp_menu"),
            InlineKeyboardButton(f"🛑 Stop Loss: -{sl:.0f}%", callback_data="set_sl_menu")
        ],
        [
            InlineKeyboardButton(f"🔄 Trailing Stop: {trailing_pct:.0f}%", callback_data="set_trailing_menu"),
            InlineKeyboardButton(f"⏱ Max Hold: {max_hold}s", callback_data="set_timeout_menu")
        ]
    ]

    if trade_mode == "futures":
        keyboard.append([
            InlineKeyboardButton(f"⚡ Futures Leverage: {leverage}x", callback_data="set_leverage_menu")
        ])

    keyboard.append([
        InlineKeyboardButton("🔙 Back to Dashboard", callback_data="refresh_dashboard")
    ])
    return InlineKeyboardMarkup(keyboard)

def get_order_amount_kb() -> InlineKeyboardMarkup:
    """Order size selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("$25", callback_data="set_amt_25"),
            InlineKeyboardButton("$50", callback_data="set_amt_50"),
            InlineKeyboardButton("$100", callback_data="set_amt_100")
        ],
        [
            InlineKeyboardButton("$250", callback_data="set_amt_250"),
            InlineKeyboardButton("$500", callback_data="set_amt_500"),
            InlineKeyboardButton("$1000", callback_data="set_amt_1000")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="open_settings")
        ]
    ])

def get_leverage_kb() -> InlineKeyboardMarkup:
    """Futures Leverage selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("2x", callback_data="set_lev_2"),
            InlineKeyboardButton("3x", callback_data="set_lev_3"),
            InlineKeyboardButton("5x", callback_data="set_lev_5"),
            InlineKeyboardButton("10x", callback_data="set_lev_10")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="open_settings")
        ]
    ])

def get_tp_kb() -> InlineKeyboardMarkup:
    """Take profit selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("+10%", callback_data="set_tp_10"),
            InlineKeyboardButton("+15%", callback_data="set_tp_15"),
            InlineKeyboardButton("+20%", callback_data="set_tp_20"),
            InlineKeyboardButton("+30%", callback_data="set_tp_30")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="open_settings")
        ]
    ])

def get_sl_kb() -> InlineKeyboardMarkup:
    """Stop loss selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("-3%", callback_data="set_sl_3"),
            InlineKeyboardButton("-5%", callback_data="set_sl_5"),
            InlineKeyboardButton("-8%", callback_data="set_sl_8"),
            InlineKeyboardButton("-10%", callback_data="set_sl_10")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="open_settings")
        ]
    ])

def get_timeout_kb() -> InlineKeyboardMarkup:
    """Max hold duration selection."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("30s", callback_data="set_to_30"),
            InlineKeyboardButton("60s", callback_data="set_to_60"),
            InlineKeyboardButton("90s", callback_data="set_to_90"),
            InlineKeyboardButton("120s", callback_data="set_to_120")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="open_settings")
        ]
    ])

def get_panic_sell_kb(trade_id: int) -> InlineKeyboardMarkup:
    """Emergency Panic Sell button for an active trade."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚨 PANIC SELL NOW (100%)", callback_data=f"panic_sell_{trade_id}")
        ]
    ])

