import asyncio
import os
import unittest
from database.db import init_db, create_or_update_user, update_user_fields, get_open_trade_by_id, get_user_trades
from services.symbol_cache import symbol_cache
from services.trade_dispatcher import trade_dispatcher
from services.position_tracker import position_tracker

class TestSimulationPipeline(unittest.TestCase):
    def test_full_snipe_flow(self):
        async def run_pipeline():
            await init_db()
            await symbol_cache.initialize()

            # Create test user
            test_uid = 99998888
            await create_or_update_user(test_uid, "trader_joe", "Joe")
            await update_user_fields(
                test_uid,
                is_active=1,
                simulation_mode=1,
                trade_mode="spot",
                order_amount_usdt=100.0,
                tp_percent=15.0,
                sl_percent=5.0
            )

            # Mock Telegram buy notifier
            notifications = []
            async def mock_buy_notifier(user_id, data):
                notifications.append(("BUY", user_id, data))

            trade_dispatcher.set_telegram_buy_notifier(mock_buy_notifier)

            # Trigger simulated listing for BTC (which is guaranteed to exist on Binance)
            print("Triggering simulated Upbit listing for BTC...")
            await trade_dispatcher.handle_listing(
                raw_title="[거래] KRW, BTC 마켓 신규 디지털 자산 추가 (BTC)",
                source="TreeNewsSim",
                coin="BTC"
            )

            # Verify notification was sent for our test user
            user_notifs = [n for n in notifications if n[1] == test_uid]
            self.assertEqual(len(user_notifs), 1)
            event_type, uid, buy_data = user_notifs[0]
            self.assertEqual(event_type, "BUY")
            self.assertEqual(uid, test_uid)
            self.assertEqual(buy_data["symbol"], "BTCUSDT")
            self.assertTrue(buy_data["is_simulation"])
            trade_id = buy_data["trade_id"]
            print(f"Simulation order opened: Trade #{trade_id} at price ${buy_data['buy_price']}")

            # Verify trade recorded in DB
            trade = await get_open_trade_by_id(trade_id)
            self.assertIsNotNone(trade)
            self.assertEqual(trade["status"], "OPEN")

            # Test Panic Sell
            user = {"telegram_id": test_uid, "simulation_mode": 1}
            print("Testing emergency panic sell execution...")
            panic_res = await position_tracker.panic_sell_manual(trade_id, user)
            self.assertTrue(panic_res["success"])
            print(f"Panic sell success! PnL: {panic_res.get('pnl_percent'):.2f}%")

            # Verify closed trade in DB
            closed_trade = await get_open_trade_by_id(trade_id)
            self.assertEqual(closed_trade["status"], "CLOSED")
            self.assertEqual(closed_trade["exit_reason"], "MANUAL_PANIC_SELL")

            from services.binance_service import binance_service
            await binance_service.close()

        asyncio.run(run_pipeline())

if __name__ == "__main__":
    unittest.main()

