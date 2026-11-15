"""
Trade Dispatcher
================
Central listing handler:
  1. Binance path  → place market buy on Binance Spot or Futures
  2. DEX fallback  → extract contract from Upbit notice → Jupiter swap on Solana

Flow:
  handle_listing(title, source, coin, notice_url, body_text)
    ├─ resolve coin to Binance symbol
    ├─ if Binance tradable → _execute_user_order() [existing path]
    └─ else               → _execute_user_dex_swap() [new DEX path]
"""

import asyncio
import time
import logging
from typing import Dict, Any, Optional, Callable
from database.db import get_active_traders, record_listing, record_trade, record_dex_trade
from database.encryption import decrypt_secret
from services.symbol_cache import symbol_cache
from services.binance_service import binance_service
from services.position_tracker import position_tracker

logger = logging.getLogger(__name__)


class TradeDispatcher:
    def __init__(self):
        self.telegram_buy_notifier: Optional[Callable] = None
        self.group_broadcaster: Optional[Callable] = None

    def set_telegram_buy_notifier(self, notifier: Callable):
        self.telegram_buy_notifier = notifier

    def set_group_broadcaster(self, broadcaster: Callable):
        self.group_broadcaster = broadcaster

    # ─────────────────────────────────────────────────────────────────────────
    # Main Entry Point
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_listing(
        self,
        raw_title: str,
        source: str,
        coin: str,
        notice_url: str = "",
        body_text: str = "",
    ):
        """
        Called when Tree News / Upbit Scraper detects a confirmed new listing.
        Broadcasts group alert and fires trades (Binance first, DEX fallback).
        """
        start_time = time.time()
        logger.info(f"=== DISPATCHING LISTING: {coin} (Source: {source}) ===")

        # 1. Resolve coin to Binance symbol (if tradable)
        sym_info = symbol_cache.resolve_symbol(coin)
        binance_symbol = sym_info["symbol"] if sym_info else None

        # 2. Record listing in database
        market_status = "USDT" if binance_symbol else "DEX_ONLY"
        await record_listing(raw_title, source, coin, market_status)

        detection_latency_ms = int((time.time() - start_time) * 1000)

        # 3. Broadcast instant alert to all registered Telegram groups
        if self.group_broadcaster:
            asyncio.create_task(
                self.group_broadcaster(
                    coin=coin,
                    binance_symbol=binance_symbol,
                    raw_title=raw_title,
                    source=source,
                    latency_ms=detection_latency_ms
                )
            )

        # 4. Get all active users
        active_users = await get_active_traders()
        if not active_users:
            logger.info("No active users enabled for auto-buying.")
            return

        logger.info(f"Executing orders for {len(active_users)} active trader(s)...")

        if binance_symbol:
            # ── BINANCE PATH ─────────────────────────────────────────────────
            logger.info(f"Resolved {coin} → Binance symbol: {binance_symbol}")
            tasks = [
                self._execute_user_order(user, binance_symbol, sym_info, start_time)
                for user in active_users
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # ── DEX FALLBACK PATH ────────────────────────────────────────────
            logger.info(f"'{coin}' NOT on Binance — engaging DEX fallback (Solana/Jupiter)...")

            # Extract contract address from notice (async, shared across all users)
            contract_info = await self._resolve_contract(coin, notice_url, body_text)

            if not contract_info:
                logger.warning(f"[DEX] No contract found for {coin} — skipping DEX trade")
                # Notify users that coin was detected but DEX trade couldn't execute
                for user in active_users:
                    if self.telegram_buy_notifier:
                        await self.telegram_buy_notifier(user["telegram_id"], {
                            "symbol": coin,
                            "dex": True,
                            "failed": True,
                            "error": f"⚠️ {coin} listed on Upbit but no contract found yet. Buy manually!",
                            "latency_ms": int((time.time() - start_time) * 1000)
                        })
                return

            if contract_info["network"] == "bitcoin":
                logger.info(f"[DEX] {coin} is on Bitcoin — no DEX support. Skipping.")
                return

            logger.info(
                f"[DEX] Contract resolved: {contract_info['network'].upper()} "
                f"{contract_info['contract'][:16]}… (source: {contract_info.get('source', '?')})"
            )

            tasks = [
                self._execute_user_dex_swap(user, coin, contract_info, start_time)
                for user in active_users
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Contract Resolution
    # ─────────────────────────────────────────────────────────────────────────

    async def _resolve_contract(
        self, coin: str, notice_url: str, body_text: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve token contract from Upbit notice. Returns contract_info dict or None."""
        try:
            from services.upbit_contract_extractor import extract_contract
            contract_info = await extract_contract(
                symbol=coin,
                notice_url=notice_url or None,
                notice_body_text=body_text or None,
            )
            return contract_info
        except Exception as e:
            logger.error(f"[DEX] Contract extraction failed for {coin}: {e}", exc_info=True)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Binance Trade Execution (unchanged)
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_user_order(
        self,
        user: Dict[str, Any],
        symbol: str,
        sym_info: Dict[str, Any],
        announcement_start_time: float
    ):
        user_id = user["telegram_id"]
        trade_mode = user.get("trade_mode", "spot")
        order_amount = float(user.get("order_amount_usdt") or 50.0)

        try:
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

                position_tracker.start_tracking(trade_id, user, trade_data)

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
                logger.error(f"Failed Binance order for user {user_id}: {err_msg}")
                if self.telegram_buy_notifier:
                    await self.telegram_buy_notifier(user_id, {
                        "symbol": symbol,
                        "failed": True,
                        "error": err_msg,
                        "latency_ms": total_latency_ms
                    })

        except Exception as e:
            logger.error(f"Unexpected error executing Binance order for user {user_id}: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # DEX Trade Execution (new)
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_user_dex_swap(
        self,
        user: Dict[str, Any],
        coin: str,
        contract_info: Dict[str, Any],
        announcement_start_time: float,
    ):
        """Execute a DEX swap for a single user using their personal Solana wallet."""
        user_id = user["telegram_id"]
        network = contract_info.get("network", "")
        contract = contract_info.get("contract", "")

        # Only Solana supported currently
        if network != "solana":
            logger.info(f"[DEX] Network '{network}' not yet supported for user {user_id}. Skipping.")
            return

        sol_amount = float(user.get("solana_buy_amount_sol") or 0.1)

        # Check wallet is provisioned
        wallet_address = user.get("solana_wallet_address", "")
        if not wallet_address:
            logger.warning(f"[DEX] User {user_id} has no Solana wallet — skipping DEX trade")
            if self.telegram_buy_notifier:
                await self.telegram_buy_notifier(user_id, {
                    "symbol": coin,
                    "dex": True,
                    "failed": True,
                    "error": "No Solana wallet found. Please restart the bot to auto-generate one.",
                    "latency_ms": int((time.time() - announcement_start_time) * 1000)
                })
            return

        try:
            from services.dex_swapper import execute_jupiter_swap
            result = await execute_jupiter_swap(
                user=user,
                contract_address=contract,
                sol_amount=sol_amount,
            )
        except Exception as e:
            logger.error(f"[DEX] execute_jupiter_swap raised for user {user_id}: {e}", exc_info=True)
            result = {"success": False, "error": str(e)}

        total_latency_ms = int((time.time() - announcement_start_time) * 1000)

        # Record in DB
        trade_id = await record_dex_trade(
            user_id=user_id,
            symbol=coin,
            network=network,
            contract_address=contract,
            tx_signature=result.get("signature", ""),
            sol_spent=sol_amount if result.get("success") else 0.0,
            tokens_received=result.get("out_tokens_approx", 0.0),
            price_impact_pct=result.get("price_impact_pct", 0.0),
            liquidity_usd=result.get("liquidity_usd", 0.0),
            contract_source=contract_info.get("source", ""),
            latency_ms=total_latency_ms,
            status="FILLED" if result.get("success") else "FAILED",
            error_msg=result.get("error", ""),
        )

        # Launch automated DEX Smart Exit Tracker (Auto TP/SL/Timeout)
        if result.get("success"):
            try:
                from services.dex_position_tracker import dex_position_tracker
                dex_position_tracker.start_tracking(
                    dex_trade_id=trade_id,
                    user=user,
                    token_mint=contract,
                    symbol=coin,
                    entry_sol_spent=sol_amount,
                    tokens_received=result.get("out_tokens_approx", 0.0)
                )
            except Exception as e:
                logger.error(f"[DEX] Failed to launch DEX position tracker: {e}")

        # Telegram notification
        if self.telegram_buy_notifier:
            if result.get("success"):
                await self.telegram_buy_notifier(user_id, {
                    "symbol": coin,
                    "dex": True,
                    "network": network.upper(),
                    "contract": contract,
                    "sol_spent": sol_amount,
                    "out_tokens_approx": result.get("out_tokens_approx", 0),
                    "price_impact_pct": result.get("price_impact_pct", 0),
                    "signature": result.get("signature", ""),
                    "solscan_url": result.get("solscan_url", ""),
                    "latency_ms": total_latency_ms,
                })
            else:
                await self.telegram_buy_notifier(user_id, {
                    "symbol": coin,
                    "dex": True,
                    "failed": True,
                    "error": result.get("error", "Unknown DEX error"),
                    "latency_ms": total_latency_ms,
                })


# Singleton instance
trade_dispatcher = TradeDispatcher()
