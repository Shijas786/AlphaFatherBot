import asyncio
import time
import logging
from typing import Dict, Any, Optional, Callable
from database.db import get_active_traders, record_listing, record_trade
from database.encryption import decrypt_secret
from services.symbol_cache import symbol_cache
from services.binance_service import binance_service
from services.position_tracker import position_tracker

logger = logging.getLogger(__name__)

class TradeDispatcher:
    def __init__(self):
        self.telegram_buy_notifier: Optional[Callable] = None

    def set_telegram_buy_notifier(self, notifier: Callable):
        self.telegram_buy_notifier = notifier

    async def handle_listing(self, raw_title: str, source: str, coin: str):
        """
        Main handler invoked when Tree News or Upbit Scraper detects a listing.
        Concurrently executes orders for all active users.
        """
        start_time = time.time()
        logger.info(f"=== DISPATCHING LISTING: {coin} (Source: {source}) ===")

        # 1. Resolve coin to Binance symbol
        sym_info = symbol_cache.resolve_symbol(coin)
        if not sym_info:
            logger.warning(f"Coin '{coin}' is NOT tradable on Binance. Skipping trade execution.")
            await record_listing(raw_title, source, coin, "UNSUPPORTED_ON_BINANCE")
            return

        binance_symbol = sym_info["symbol"]
        logger.info(f"Resolved {coin} -> Binance symbol: {binance_symbol}")

        # 2. Record listing in database
        await record_listing(raw_title, source, coin, "USDT")

        # 3. Get all active users
        active_users = await get_active_traders()
        if not active_users:
            logger.info("No active users enabled for auto-buying.")
            return

        logger.info(f"Executing orders for {len(active_users)} active trader(s)...")

        # 4. Fire orders concurrently for all users
        tasks = [self._execute_user_order(user, binance_symbol, sym_info, start_time) for user in active_users]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_user_order(
        self,
        user: Dict[str, Any],
        symbol: str,
        sym_info: Dict[str, Any],
        announcement_start_time: float
    ):
        user_id = user["telegram_id"]
        trade_mode = user.get("trade_mode", "spot")
        order_amount = float(user.get("order_amount_usdt", 50.0))

        try:
            # REAL BINANCE TRADING
            api_key = decrypt_secret(user.get("binance_api_key", ""))
            api_secret = decrypt_secret(user.get("binance_api_secret", ""))

            if not api_key or not api_secret:
                logger.warning(f"User {user_id} has bot enabled but missing API credentials.")
                if self.telegram_buy_notifier:
                    await self.telegram_buy_notifier(user_id, {
                        "symbol": symbol,
                        "failed": True,
                        "error": "Binance API Key not connected! Please add your API key in settings.",
                        "latency_ms": int((time.time() - announcement_start_time) * 1000)
                    })
                return

            if trade_mode == "futures":
                order_res = await binance_service.place_futures_market_buy(
                    api_key=api_key,
                    api_secret=api_secret,
                    symbol=symbol,
                    usdt_amount=order_amount,
                    leverage=user.get("futures_leverage", 3),
                    step_size=sym_info["step_size"]
                )
            else:
                order_res = await binance_service.place_spot_market_buy(
                    api_key=api_key,
                    api_secret=api_secret,
                    symbol=symbol,
                    usdt_amount=order_amount
                )

            total_latency_ms = int((time.time() - announcement_start_time) * 1000)

            if order_res.get("success"):
                trade_id = await record_trade(
                    user_id=user_id,
                    symbol=symbol,
                    trade_mode=trade_mode,
                    side="BUY",
                    order_id=order_res.get("order_id", ""),
                    buy_price=order_res.get("avg_price", 0.0),
                    quantity=order_res.get("executed_qty", 0.0),
                    usdt_spent=order_res.get("usdt_spent", order_amount),
                    status="OPEN"
                )

                trade_data = {
                    "symbol": symbol,
                    "trade_mode": trade_mode,
                    "buy_price": order_res.get("avg_price", 0.0),
                    "quantity": order_res.get("executed_qty", 0.0),
                    "usdt_spent": order_res.get("usdt_spent", order_amount)
                }

                # Start smart exit monitoring
                position_tracker.start_tracking(trade_id, user, trade_data)

                # Send Telegram notification
                if self.telegram_buy_notifier:
                    await self.telegram_buy_notifier(user_id, {
                        "trade_id": trade_id,
                        "symbol": symbol,
                        "trade_mode": trade_mode,
                        "buy_price": order_res.get("avg_price", 0.0),
                        "quantity": order_res.get("executed_qty", 0.0),
                        "usdt_spent": order_res.get("usdt_spent", order_amount),
                        "latency_ms": total_latency_ms
                    })
            else:
                err_msg = order_res.get("error", "Unknown error")
                logger.error(f"Failed order for user {user_id}: {err_msg}")
                if self.telegram_buy_notifier:
                    await self.telegram_buy_notifier(user_id, {
                        "symbol": symbol,
                        "failed": True,
                        "error": err_msg,
                        "latency_ms": total_latency_ms
                    })

        except Exception as e:
            logger.error(f"Unexpected error executing order for user {user_id}: {e}")

# Singleton instance
trade_dispatcher = TradeDispatcher()

