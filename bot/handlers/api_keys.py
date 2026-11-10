from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from database.db import update_user_fields, get_user
from database.encryption import encrypt_secret
from services.binance_service import binance_service
from bot.keyboards import get_main_dashboard_kb

STATE_WAITING_API_KEY = 1
STATE_WAITING_API_SECRET = 2

async def start_api_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for connecting Binance API."""
    query = update.callback_query
    await query.answer()

    text = (
        "🔐 *CONNECT YOUR BINANCE API KEY*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "To allow the bot to snipe listings for you:\n\n"
        "1️⃣ Log in to Binance -> **API Management**\n"
        "2️⃣ Create API Key (System generated)\n"
        "3️⃣ Permissions required:\n"
        "   • ✅ Enable Reading\n"
        "   • ✅ Enable Spot & Margin Trading\n"
        "   • ✅ Enable Futures (if trading futures)\n"
        "   • ❌ *DISABLE WITHDRAWALS* (Never give withdrawal access!)\n\n"
        "👉 **Send your Binance API KEY as a reply:**\n\n"
        "_(Send /cancel anytime to exit)_"
    )
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_api_setup")]])
    await query.edit_message_text(text, reply_markup=cancel_kb, parse_mode="Markdown")
    return STATE_WAITING_API_KEY

async def receive_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and store API key in context."""
    api_key = update.message.text.strip()
    if not api_key or len(api_key) < 20:
        await update.message.reply_text("⚠️ Invalid API Key format. Please send a valid Binance API Key (or /cancel):")
        return STATE_WAITING_API_KEY

    context.user_data["temp_api_key"] = api_key

    # Prompt for secret
    text = (
        "✅ API Key received.\n\n"
        "👉 Now send your **Binance API SECRET**:\n\n"
        "🔒 _Note: The message containing your secret will be automatically deleted immediately after reading for your privacy and security._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return STATE_WAITING_API_SECRET

async def receive_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive secret, validate with Binance, and encrypt to DB."""
    api_secret = update.message.text.strip()
    api_key = context.user_data.get("temp_api_key", "")

    # Immediately delete user message containing secret
    try:
        await update.message.delete()
    except Exception:
        pass

    if not api_secret or len(api_secret) < 20:
        await update.message.reply_text("⚠️ Invalid Secret Key length. Please re-send or /cancel:")
        return STATE_WAITING_API_SECRET

    status_msg = await update.message.reply_text("🔄 *Validating credentials with Binance...*", parse_mode="Markdown")

    user = await get_user(update.effective_user.id)
    is_futures = (user.get("trade_mode") == "futures") if user else False

    is_valid, err_msg = await binance_service.test_credentials(api_key, api_secret, check_futures=is_futures)

    if not is_valid:
        await status_msg.edit_text(
            f"❌ *Binance Authentication Failed!*\n\n`{err_msg}`\n\n"
            "Please check that your API key is active and IP restrictions are set appropriately.",
            parse_mode="Markdown"
        )
        context.user_data.clear()
        return ConversationHandler.END

    # Encrypt keys using AES-GCM
    encrypted_key = encrypt_secret(api_key)
    encrypted_secret = encrypt_secret(api_secret)

    await update_user_fields(
        update.effective_user.id,
        binance_api_key=encrypted_key,
        binance_api_secret=encrypted_secret
    )
    context.user_data.clear()

    await status_msg.edit_text(
        "🎉 *Binance API Successfully Connected!*\n\n"
        "• Your credentials are encrypted at rest with AES-256.\n"
        "• You can now enable the bot from the dashboard.\n\n"
        "Use /start to open your dashboard.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_api_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel API setup."""
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer("API setup cancelled.")
        user = await get_user(update.callback_query.from_user.id)
        from bot.handlers.start import format_dashboard_text
        text = await format_dashboard_text(user)
        await update.callback_query.edit_message_text(text, reply_markup=get_main_dashboard_kb(user), parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text("API setup cancelled. Use /start to return.")
    return ConversationHandler.END

