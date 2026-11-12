import logging
from telegram import Update
from telegram.ext import ContextTypes
import config
from database.db import get_all_users, get_active_traders, get_global_profit_sharing_summary, get_group_stats
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
    """View bot metrics and profit sharing ledger."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    all_users = await get_all_users()
    active_users = await get_active_traders()
    profit_summary = await get_global_profit_sharing_summary()
    group_stats = await get_group_stats()

    total_profits = profit_summary.get("total_user_profits", 0.0)
    accrued_fees = profit_summary.get("total_fees_accrued", 0.0)
    volume = profit_summary.get("total_volume", 0.0)

    top_text = ""
    for u in profit_summary.get("top_earning_users", []):
        handle = f"@{u['username']}" if u.get("username") else f"`{u['telegram_id']}`"
        top_text += f" • {handle}: `+${u['total_pnl']:.2f}` (Fee: `${u['total_fees']:.2f}`)\n"

    if not top_text:
        top_text = " • No winning trades recorded yet.\n"

    text = (
        "💼 *CAPO ADMIN: PROFIT SHARING LEDGER*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Registered Users:* `{len(all_users)}`\n"
        f"🟢 *Active Snipers:* `{len(active_users)}`\n"
        f"🏛 *Broadcast Groups:* `{group_stats['active_groups']}`\n"
        f"📦 *Total Volume Traded:* `${volume:,.2f} USDT`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Total User Net Profits:* `+${total_profits:,.2f} USDT`\n"
        f"💵 *Accrued Platform Share (10%):* `${accrued_fees:,.2f} USDT`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 *Top Earning Traders:*\n"
        f"{top_text}"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 _Fee tracking is calculated automatically. Collection can be initiated anytime._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

