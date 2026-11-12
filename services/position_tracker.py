import asyncio
import time
import json
import logging
from typing import Dict, Any, Optional, Callable
import aiohttp
from database.db import close_trade, get_open_trade_by_id
from database.encryption import decrypt_secret
from services.binance_service import binance_service
from services.symbol_cache import symbol_cache

logger = logging.getLogger(__name__)

class PositionTracker:
    def __init__(self):
        # Active trade tracking tasks: trade_id -> task
        self.active_tasks: Dict[int, asyncio.Task] = {}
        # Callback to notify Telegram user when trade exits: callback(user_id, trade_dict)
        self.telegram_notifier: Optional[Callable] = None

    def set_telegram_notifier(self, notifier: Callable):
        self.telegram_notifier = notifier

    def start_tracking(self, trade_id: int, user: Dict[str, Any], trade_data: Dict[str, Any]):
        """Launch an async tracking worker for this specific trade."""
        task = asyncio.create_task(self._track_position(trade_id, user, trade_data))
        self.active_tasks[trade_id] = task

    async def panic_sell_manual(self, trade_id: int, user: Dict[str, Any]) -> Dict[str, Any]:
        """Manually trigger immediate sell from Telegram button."""
        # Cancel tracking loop if running
        if trade_id in self.active_tasks:
            self.active_tasks[trade_id].cancel()
            self.active_tasks.pop(trade_id, None)

        trade = await get_open_trade_by_id(trade_id)
        if not trade or trade.get("status") != "OPEN":
            return {"success": False, "error": "Trade is already closed or not found."}

        return await self._execute_exit(trade_id, user, trade, exit_reason="MANUAL_PANIC_SELL")

    async def _track_position(self, trade_id: int, user: Dict[str, Any], trade_data: Dict[str, Any]):
        symbol = trade_data["symbol"]
        is_futures = (trade_data["trade_mode"] == "futures")
        entry_price = float(trade_data["buy_price"])
        quantity = float(trade_data["quantity"])
        is_simulation = bool(user.get("simulation_mode", 0))

        tp_percent = float(user.get("tp_percent", 15.0))
        sl_percent = float(user.get("sl_percent", 5.0))
        trailing_stop_pct = float(user.get("trailing_stop_percent", 4.0))
        trailing_act_pct = float(user.get("trailing_activation_percent", 8.0))
        max_hold_sec = int(user.get("max_hold_seconds", 90))

        start_time = time.time()
        highest_price = entry_price
        trailing_armed = False

        logger.info(f"[Trade #{trade_id}] Position tracking started for {symbol} (Entry: {entry_price})")

        # Try connecting to Binance WebSocket for sub-50ms tick-by-tick real-time monitoring
        ws_url = (
            f"wss://fstream.binance.com/ws/{symbol.lower()}@trade"
            if is_futures
            else f"wss://stream.binance.com:9443/ws/{symbol.lower()}@trade"
        )

        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=None)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(ws_url) as ws:
                    logger.info(f"[Trade #{trade_id}] Connected to Binance real-time WebSocket ticker stream for {symbol}!")
                    
                    async for msg in ws:
                        elapsed = time.time() - start_time
                        if elapsed >= max_hold_sec:
                            logger.info(f"[Trade #{trade_id}] Max hold timeout reached ({elapsed:.0f}s)")
                            await self._execute_exit(trade_id, user, trade_data, exit_reason="TIMEOUT_REACHED", exit_price=highest_price)
                            return

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            current_price = float(data.get("p", 0.0))
                            if current_price <= 0:
                                continue

                            if current_price > highest_price:
                                highest_price = current_price

                            raw_pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                            leverage = user.get("futures_leverage", 1) if is_futures else 1
                            effective_pnl_pct = raw_pnl_pct * leverage

                            # Arm trailing stop
                            if effective_pnl_pct >= trailing_act_pct and not trailing_armed:
                                trailing_armed = True
                                logger.info(f"[Trade #{trade_id}] Trailing stop ARMED at {effective_pnl_pct:.2f}%")

                            # Check trailing stop trigger
                            if trailing_armed:
                                pullback_from_peak = ((highest_price - current_price) / highest_price) * 100.0 * leverage
                                if pullback_from_peak >= trailing_stop_pct:
                                    logger.info(f"[Trade #{trade_id}] Trailing stop TRIGGERED (Peak: {highest_price}, Current: {current_price})")
                                    await self._execute_exit(trade_id, user, trade_data, exit_reason="TRAILING_STOP", exit_price=current_price)
                                    return

                            # Hard TP
                            if effective_pnl_pct >= tp_percent:
                                logger.info(f"[Trade #{trade_id}] Hard Take Profit hit (+{effective_pnl_pct:.2f}%)")
                                await self._execute_exit(trade_id, user, trade_data, exit_reason="TAKE_PROFIT", exit_price=current_price)
                                return

                            # Hard SL
                            if effective_pnl_pct <= -sl_percent:
                                logger.info(f"[Trade #{trade_id}] Hard Stop Loss hit ({effective_pnl_pct:.2f}%)")
                                await self._execute_exit(trade_id, user, trade_data, exit_reason="STOP_LOSS", exit_price=current_price)
                                return

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"[Trade #{trade_id}] Binance WS closed, switching to REST polling...")
                            break
        except Exception as ws_err:
            logger.warning(f"[Trade #{trade_id}] WebSocket price stream failed ({ws_err}), falling back to REST polling...")

        # Fallback REST Polling Loop if WebSocket is unavailable
        while True:
            try:
                await asyncio.sleep(0.8)
                elapsed = time.time() - start_time

                current_price = await binance_service.get_symbol_price(symbol, is_futures=is_futures)
                if current_price <= 0:
                    continue

                if current_price > highest_price:
                    highest_price = current_price

                raw_pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                leverage = user.get("futures_leverage", 1) if is_futures else 1
                effective_pnl_pct = raw_pnl_pct * leverage

                if effective_pnl_pct >= trailing_act_pct and not trailing_armed:
                    trailing_armed = True
                    logger.info(f"[Trade #{trade_id}] Trailing stop ARMED at {effective_pnl_pct:.2f}%")

                if trailing_armed:
                    pullback_from_peak = ((highest_price - current_price) / highest_price) * 100.0 * leverage
                    if pullback_from_peak >= trailing_stop_pct:
                        logger.info(f"[Trade #{trade_id}] Trailing stop TRIGGERED (Peak: {highest_price}, Current: {current_price})")
                        await self._execute_exit(trade_id, user, trade_data, exit_reason="TRAILING_STOP", exit_price=current_price)
                        break

                if effective_pnl_pct >= tp_percent:
                    logger.info(f"[Trade #{trade_id}] Hard Take Profit hit (+{effective_pnl_pct:.2f}%)")
                    await self._execute_exit(trade_id, user, trade_data, exit_reason="TAKE_PROFIT", exit_price=current_price)
                    break

                if effective_pnl_pct <= -sl_percent:
                    logger.info(f"[Trade #{trade_id}] Hard Stop Loss hit ({effective_pnl_pct:.2f}%)")
                    await self._execute_exit(trade_id, user, trade_data, exit_reason="STOP_LOSS", exit_price=current_price)
                    break

                if elapsed >= max_hold_sec:
                    logger.info(f"[Trade #{trade_id}] Max hold timeout reached ({elapsed:.0f}s)")
                    await self._execute_exit(trade_id, user, trade_data, exit_reason="TIMEOUT_REACHED", exit_price=current_price)
                    break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Trade #{trade_id}] Error in position tracking loop: {e}")
                await asyncio.sleep(2)

        self.active_tasks.pop(trade_id, None)

    async def _execute_exit(
        self,
        trade_id: int,
        user: Dict[str, Any],
        trade_data: Dict[str, Any],
        exit_reason: str,
        exit_price: float = 0.0
    ) -> Dict[str, Any]:
        """Execute market sell order and close trade in database."""
        symbol = trade_data["symbol"]
        is_futures = (trade_data["trade_mode"] == "futures")
        quantity = float(trade_data["quantity"])
        entry_price = float(trade_data["buy_price"])
        usdt_spent = float(trade_data["usdt_spent"])

        api_key = decrypt_secret(user.get("binance_api_key", ""))
        api_secret = decrypt_secret(user.get("binance_api_secret", ""))

        # Step size info for symbol
        sym_info = symbol_cache.resolve_symbol(symbol, trade_mode=trade_data["trade_mode"])
        step_size = sym_info["step_size"] if sym_info else 0.001

        sell_order_id = ""
        sell_price = exit_price

        # Real Binance Market Sell
        if is_futures:
            sell_res = await binance_service.place_futures_market_sell(
                api_key=api_key,
                api_secret=api_secret,
                symbol=symbol,
                quantity=quantity,
                step_size=step_size
            )
        else:
            sell_res = await binance_service.place_spot_market_sell(
                api_key=api_key,
                api_secret=api_secret,
                symbol=symbol,
                quantity=quantity,
                step_size=step_size
            )

        if sell_res.get("success"):
            sell_order_id = sell_res.get("order_id", "")
            sell_price = sell_res.get("avg_price", sell_price)
            if sell_price <= 0:
                sell_price = await binance_service.get_symbol_price(symbol, is_futures=is_futures)

            pnl_percent = ((sell_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
            if is_futures:
                pnl_percent *= user.get("futures_leverage", 1)
            pnl_usdt = usdt_spent * (pnl_percent / 100.0)
            res = {"success": True, "pnl_percent": pnl_percent, "pnl_usdt": pnl_usdt}
        else:
            logger.error(f"[Trade #{trade_id}] Sell order failed: {sell_res.get('error')}")
            # Fallback calculate with mark price
            if sell_price <= 0:
                sell_price = await binance_service.get_symbol_price(symbol, is_futures=is_futures)
            pnl_percent = ((sell_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
            if is_futures:
                pnl_percent *= user.get("futures_leverage", 1)
            pnl_usdt = usdt_spent * (pnl_percent / 100.0)
            res = {"success": False, "error": sell_res.get("error")}

        # Update database
        await close_trade(
            trade_id=trade_id,
            sell_price=sell_price,
            sell_order_id=sell_order_id,
            pnl_percent=pnl_percent,
            pnl_usdt=pnl_usdt,
            exit_reason=exit_reason,
            status="CLOSED"
        )

        # Notify Telegram user
        if self.telegram_notifier:
            try:
                exit_info = {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "trade_mode": trade_data["trade_mode"],
                    "buy_price": entry_price,
                    "sell_price": sell_price,
                    "pnl_percent": pnl_percent,
                    "pnl_usdt": pnl_usdt,
                    "exit_reason": exit_reason,
                    "is_simulation": is_simulation
                }
                asyncio.create_task(self.telegram_notifier(user["telegram_id"], exit_info))
            except Exception as e:
                logger.error(f"Error sending exit notification to user {user['telegram_id']}: {e}")

        return res

# Singleton instance
position_tracker = PositionTracker()

