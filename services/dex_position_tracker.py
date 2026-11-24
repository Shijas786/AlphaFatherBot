"""
DEX Position Tracker & Smart Exit Engine
=========================================
Monitors open DEX positions (Solana Jupiter swaps) in real-time.
Automatically triggers take-profit or stop-loss exits using Jupiter.
"""

import asyncio
import html
import time
import logging
from typing import Dict, Any, Optional, Callable
import aiohttp
from services.dex_swapper import execute_jupiter_sell, get_spl_raw_balance, JUPITER_QUOTE_URL, SOL_MINT, LAMPORTS_PER_SOL, _HEADERS
from database.db import close_dex_trade

logger = logging.getLogger(__name__)

class DEXPositionTracker:
    def __init__(self):
        self.telegram_notifier: Optional[Callable] = None
        self.active_tasks: Dict[str, asyncio.Task] = {}

    def set_telegram_notifier(self, notifier: Callable):
        self.telegram_notifier = notifier

    def start_tracking(self, dex_trade_id: int, user: Dict[str, Any], token_mint: str, symbol: str, entry_sol_spent: float, tokens_received: float):
        """Start a background exit monitoring loop for an executed DEX trade."""
        key = f"{user['telegram_id']}_{dex_trade_id}_{token_mint}"
        task = asyncio.create_task(
            self._monitor_position(key, dex_trade_id, user, token_mint, symbol, entry_sol_spent, tokens_received)
        )
        self.active_tasks[key] = task

    async def _get_current_sol_value(self, token_mint: str, raw_token_amount: int) -> float:
        """Query Jupiter for current SOL return for this amount of tokens."""
        if raw_token_amount <= 0:
            return 0.0
        try:
            params = {
                "inputMint": token_mint,
                "outputMint": SOL_MINT,
                "amount": raw_token_amount,
                "slippageBps": 500,
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(JUPITER_QUOTE_URL, params=params, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        out_lamports = int(data.get("outAmount", 0))
                        return out_lamports / LAMPORTS_PER_SOL
        except Exception:
            pass
        return 0.0

    async def _monitor_position(
        self,
        key: str,
        dex_trade_id: int,
        user: Dict[str, Any],
        token_mint: str,
        symbol: str,
        entry_sol_spent: float,
        tokens_received: float
    ):
        user_id = user["telegram_id"]
        tp_pct = float(user.get("tp_percent", 50.0))    # e.g. +50% TP
        sl_pct = float(user.get("sl_percent", 15.0))    # e.g. -15% SL

        start_time = time.time()
        wallet_address = user.get("solana_wallet_address", "")
        logger.info(f"[DEXTracker] Monitoring {symbol} for user {user_id} (TP: +{tp_pct}%, SL: -{sl_pct}%)")

        # Query on-chain SPL token balance to get exact token amount regardless of decimals (6, 8, 9, etc.)
        raw_token_amount = 0
        for _ in range(6):
            if wallet_address:
                raw_token_amount, _ = await get_spl_raw_balance(wallet_address, token_mint)
                if raw_token_amount > 0:
                    break
            await asyncio.sleep(1.0)

        # Fallback if on-chain RPC indexer is slightly delayed
        if raw_token_amount <= 0:
            raw_token_amount = int(tokens_received * 1_000_000)

        while True:
            await asyncio.sleep(2.5)
            elapsed = time.time() - start_time

            # 1. Check current value
            current_sol_val = await self._get_current_sol_value(token_mint, raw_token_amount)
            if current_sol_val <= 0:
                continue

            pnl_pct = ((current_sol_val - entry_sol_spent) / entry_sol_spent) * 100.0 if entry_sol_spent > 0 else 0.0

            # 2. Check Take Profit
            if pnl_pct >= tp_pct:
                exit_reason = f"TAKE_PROFIT (+{pnl_pct:.1f}%)"
                break

            # 3. Check Stop Loss
            if pnl_pct <= -sl_pct:
                exit_reason = f"STOP_LOSS ({pnl_pct:.1f}%)"
                break

        # Execute Auto-Sell via Jupiter
        logger.info(f"[DEXTracker] Triggering auto-exit for {symbol}: {exit_reason}")
        res = await execute_jupiter_sell(user, token_mint, percentage=1.0)
        sol_received = float(res.get("sol_received", current_sol_val) or 0.0)

        # Update DEX trade status in SQLite database
        try:
            await close_dex_trade(
                dex_trade_id=dex_trade_id,
                sol_received=sol_received,
                pnl_percent=pnl_pct,
                exit_reason=exit_reason,
                exit_signature=res.get("signature", ""),
                status="CLOSED" if res.get("success") else "FAILED_EXIT"
            )
        except Exception as e:
            logger.error(f"[DEXTracker] Error updating dex_trade in database: {e}")

        if self.telegram_notifier:
            try:
                sign = "+" if pnl_pct >= 0 else ""
                icon = "🎉" if pnl_pct >= 0 else "🛑"
                text = (
                    f"⚠️ <b>DEX AUTO-SELL FAILED!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🪙 <b>Token:</b> #{symbol}\n"
                    f"📈 <b>PnL at trigger:</b> <code>{sign}{pnl_pct:.2f}%</code>\n"
                    f"📌 <b>Reason:</b> <code>{exit_reason}</code>\n"
                    f"❌ <b>Error:</b> <code>{html.escape(str(res.get('error', 'Unknown error')))}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"The tokens are still in your wallet and are no longer monitored. Sell them manually."
                ) if not res.get("success") else (
                    f"{icon} <b>DEX POSITION CLOSED!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🪙 <b>Token:</b> #{symbol}\n"
                    f"💸 <b>Entry:</b> <code>{entry_sol_spent:.4f} SOL</code>\n"
                    f"💰 <b>Exit:</b> <code>{sol_received:.4f} SOL</code>\n"
                    f"📈 <b>PnL:</b> <code>{sign}{pnl_pct:.2f}%</code>\n"
                    f"📌 <b>Reason:</b> <code>{exit_reason}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔗 <a href=\"{res.get('solscan_url', '')}\">View Solscan Exit</a>"
                )
                await self.telegram_notifier(user_id, text)
            except Exception as e:
                logger.error(f"[DEXTracker] Notification error: {e}")

        self.active_tasks.pop(key, None)

dex_position_tracker = DEXPositionTracker()
