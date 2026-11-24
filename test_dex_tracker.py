import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services import dex_position_tracker as module
from services.dex_position_tracker import DEXPositionTracker


class TestDexExitNotification(unittest.TestCase):
    def _run_exit(self, sell_result):
        tracker = DEXPositionTracker()
        notifier = AsyncMock()
        tracker.set_telegram_notifier(notifier)
        user = {"telegram_id": 1, "tp_percent": 50.0, "sl_percent": 15.0, "solana_wallet_address": "wallet"}

        with patch.object(module, "get_spl_raw_balance", AsyncMock(return_value=(1000, 6))), \
             patch.object(module.asyncio, "sleep", AsyncMock()), \
             patch.object(tracker, "_get_current_sol_value", AsyncMock(return_value=2.0)), \
             patch.object(module, "execute_jupiter_sell", AsyncMock(return_value=sell_result)), \
             patch.object(module, "close_dex_trade", AsyncMock()) as close:
            asyncio.run(tracker._monitor_position("k", 7, user, "mint", "TKN", 1.0, 0.001))

        return notifier.call_args.args[1], close.call_args.kwargs["status"]

    def test_successful_exit_reports_position_closed(self):
        text, status = self._run_exit({"success": True, "sol_received": 2.0, "signature": "sig", "solscan_url": "https://solscan.io/tx/sig"})
        self.assertEqual(status, "CLOSED")
        self.assertIn("DEX POSITION CLOSED", text)

    def test_failed_exit_is_not_reported_as_closed(self):
        text, status = self._run_exit({"success": False, "error": "Solana network transaction failed"})
        self.assertEqual(status, "FAILED_EXIT")
        self.assertNotIn("DEX POSITION CLOSED", text)
        self.assertIn("AUTO-SELL FAILED", text)
        self.assertIn("Solana network transaction failed", text)


if __name__ == "__main__":
    unittest.main()
