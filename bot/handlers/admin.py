import logging
from telegram import Update
from telegram.ext import ContextTypes
import config
from database.db import get_all_users, get_active_traders
from services.trade_dispatcher import trade_dispatcher

logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    return config.ADMIN_USER_ID and user_id == config.ADMIN_USER_ID

async def admin_simulate_listing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin command to simulate a listing announcement test.
    Usage: /simulate_listing <COIN>
    Example: /simulate_listing DRIFT
    """
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized. Admin command only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/simulate_listing <COIN>`\nExample: `/simulate_listing TIA`", parse_mode="Markdown")
        return

    coin = context.args[0].upper().strip()
    sim_title = f"[거래] KRW, BTC 마켓 디지털 자산 추가 ({coin})"

    await update.message.reply_text(f"🧪 *Simulating Listing Announcement:*\n`{sim_title}`\n\nFiring orders for active users...", parse_mode="Markdown")

    # Dispatch listing
    await trade_dispatcher.handle_listing(raw_title=sim_title, source="AdminSimulate", coin=coin)

async def admin_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast announcement to all users: /broadcast <message>"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode="Markdown")
        return

    msg = " ".join(context.args)
    users = await get_all_users()
    sent_count = 0

    for u in users:
        try:
            await context.bot.send_message(
                chat_id=u["telegram_id"],
                text=f"📢 *BROADCAST ANNOUNCEMENT*\n━━━━━━━━━━━━━━━━━━━━━━\n{msg}",
                parse_mode="Markdown"
            )
            sent_count += 1
        except Exception:
            pass

    await update.message.reply_text(f"✅ Broadcast sent to {sent_count}/{len(users)} users.")

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View bot metrics."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    all_users = await get_all_users()
    active_users = await get_active_traders()

    text = (
        "📈 *ADMIN METRICS & SYSTEM STATUS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Registered Users:* `{len(all_users)}`\n"
        f"🟢 *Active Traders:* `{len(active_users)}`\n"
        f"📡 *Tree News WS:* `{config.TREE_NEWS_WS_URL}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Use `/simulate_listing <COIN>` to test execution."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

