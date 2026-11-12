import asyncio
import logging
import signal
import sys
import config
from database.db import init_db
from database.encryption import get_fernet
from services.symbol_cache import symbol_cache
from services.tree_news_listener import TreeNewsListener
from services.upbit_notice_scraper import UpbitNoticeScraper
from services.trade_dispatcher import trade_dispatcher
from services.position_tracker import position_tracker
from bot.telegram_bot import build_telegram_app, TelegramNotifier
from webapp.server import webapp_runner

# Configure logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("main")

async def main():
    logger.info("Initializing Upbit Listing Sniper Bot...")

    # 1. Verify Encryption Key
    try:
        get_fernet()
    except Exception as e:
        logger.error(f"Encryption key check failed: {e}")
        return

    # 2. Initialize Database
    await init_db()
    logger.info("Database initialized successfully.")

    # 3. Pre-load Binance Symbols into RAM Cache
    logger.info("Loading Binance Spot & Futures market symbols into RAM...")
    await symbol_cache.initialize()

    # 4. Initialize Telegram Bot
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not configured in .env! Please set your token.")
        return

    app = build_telegram_app()
    notifier = TelegramNotifier(app.bot)
    trade_dispatcher.set_telegram_buy_notifier(notifier.notify_buy)
    trade_dispatcher.set_group_broadcaster(notifier.broadcast_listing_to_groups)
    position_tracker.set_telegram_notifier(notifier.notify_exit)

    # 5. Define Centralized Listing Callback
    async def on_listing_announcement(title: str, source: str, coin: str):
        logger.info(f"==> NEW LISTING DETECTED via {source}: {coin} - '{title}'")
        await trade_dispatcher.handle_listing(raw_title=title, source=source, coin=coin)

    # 6. Initialize Listeners
    tree_news_listener = TreeNewsListener(on_listing_announcement)
    upbit_scraper = UpbitNoticeScraper(on_listing_announcement, poll_interval=1.5)

    # 7. Start Telegram Mini App Web Server
    await webapp_runner.start()

    # Background tasks
    tasks = []
    tasks.append(asyncio.create_task(tree_news_listener.start()))
    tasks.append(asyncio.create_task(upbit_scraper.start()))

    # Periodic background symbol cache refresher (every 1 hour)
    async def periodic_cache_refresh():
        while True:
            await asyncio.sleep(3600)
            logger.info("Performing scheduled Binance symbol cache refresh...")
            await symbol_cache.refresh_cache()

    tasks.append(asyncio.create_task(periodic_cache_refresh()))

    # Start Telegram Bot
    logger.info("Starting Telegram Bot Polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot is fully operational and listening for Upbit listings!")

    # Keep alive until cancelled
    stop_event = asyncio.Event()

    def handle_exit():
        logger.info("Shutdown signal received...")
        tree_news_listener.stop()
        upbit_scraper.stop()
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_exit)
        except NotImplementedError:
            pass

    await stop_event.wait()

    # Graceful teardown
    logger.info("Shutting down background workers...")
    for t in tasks:
        t.cancel()
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    await webapp_runner.stop()
    from services.binance_service import binance_service
    await binance_service.close()
    logger.info("Shutdown completed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
