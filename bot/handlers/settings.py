from telegram import Update
from telegram.ext import ContextTypes
from database.db import get_user, update_user_fields
from bot.keyboards import (
    get_settings_kb,
    get_order_amount_kb,
    get_tp_kb,
    get_sl_kb,
    get_timeout_kb,
    get_leverage_kb
)

async def open_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open settings main menu."""
    query = update.callback_query
    await query.answer()
    user = await get_user(query.from_user.id)
    if not user:
        return
    text = (
        "⚙️ *STRATEGY & TRADING SETTINGS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Configure your risk parameters, trade size, and exit rules below:"
    )
    await query.edit_message_text(text, reply_markup=get_settings_kb(user), parse_mode="Markdown")

async def set_amount_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "💵 *Select Buy Order Size (USDT):*\nChoose how much USDT to spend on each new listing:"
    await query.edit_message_text(text, reply_markup=get_order_amount_kb(), parse_mode="Markdown")

async def set_amount_val_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    val = float(query.data.replace("set_amt_", ""))
    await update_user_fields(query.from_user.id, order_amount_usdt=val)
    await query.answer(f"Order size set to ${val:.0f} USDT")
    user = await get_user(query.from_user.id)
    await query.edit_message_text("⚙️ *Settings Updated!*", reply_markup=get_settings_kb(user), parse_mode="Markdown")

async def set_tp_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "🎯 *Select Hard Take Profit (%):*\nBot will immediately sell 100% when this target is reached:"
    await query.edit_message_text(text, reply_markup=get_tp_kb(), parse_mode="Markdown")

async def set_tp_val_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    val = float(query.data.replace("set_tp_", ""))
    await update_user_fields(query.from_user.id, tp_percent=val)
    await query.answer(f"Take Profit set to +{val:.0f}%")
    user = await get_user(query.from_user.id)
    await query.edit_message_text("⚙️ *Settings Updated!*", reply_markup=get_settings_kb(user), parse_mode="Markdown")

async def set_sl_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "🛑 *Select Hard Stop Loss (%):*\nBot will immediately cut loss if price drops below this:"
    await query.edit_message_text(text, reply_markup=get_sl_kb(), parse_mode="Markdown")

async def set_sl_val_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    val = float(query.data.replace("set_sl_", ""))
    await update_user_fields(query.from_user.id, sl_percent=val)
    await query.answer(f"Stop Loss set to -{val:.0f}%")
    user = await get_user(query.from_user.id)
    await query.edit_message_text("⚙️ *Settings Updated!*", reply_markup=get_settings_kb(user), parse_mode="Markdown")

async def set_timeout_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "⏱ *Select Maximum Hold Duration (Seconds):*\nIf TP/SL is not hit within this time, sell at market to prevent post-pump bleed:"
    await query.edit_message_text(text, reply_markup=get_timeout_kb(), parse_mode="Markdown")

async def set_timeout_val_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    val = int(query.data.replace("set_to_", ""))
    await update_user_fields(query.from_user.id, max_hold_seconds=val)
    await query.answer(f"Max Hold duration set to {val} seconds")
    user = await get_user(query.from_user.id)
    await query.edit_message_text("⚙️ *Settings Updated!*", reply_markup=get_settings_kb(user), parse_mode="Markdown")

async def set_leverage_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "⚡ *Select Futures Leverage:*\n(Careful: Higher leverage means faster liquidations)"
    await query.edit_message_text(text, reply_markup=get_leverage_kb(), parse_mode="Markdown")

async def set_leverage_val_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    val = int(query.data.replace("set_lev_", ""))
    await update_user_fields(query.from_user.id, futures_leverage=val)
    await query.answer(f"Leverage set to {val}x")
    user = await get_user(query.from_user.id)
    await query.edit_message_text("⚙️ *Settings Updated!*", reply_markup=get_settings_kb(user), parse_mode="Markdown")

