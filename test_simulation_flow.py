import asyncio
import os
import unittest
from unittest.mock import patch
from database.db import init_db, create_or_update_user, update_user_fields, get_open_trade_by_id, get_user_trades
from database.encryption import encrypt_secret
from services.symbol_cache import symbol_cache
from services.trade_dispatcher import trade_dispatcher
from services.position_tracker import position_tracker
from services.binance_service import binance_service

class TestTradingPipeline(unittest.TestCase):
    def test_full_snipe_flow(self):
        async def run_pipeline():
            await init_db()
            await symbol_cache.initialize()

            # Create test user with encrypted credentials
            test_uid = 99998888
            await create_or_update_user(test_uid, "trader_joe", "Joe")
            await update_user_fields(
                test_uid,
                is_active=1,
                trade_mode="spot",
                order_amount_usdt=100.0,
                tp_percent=15.0,
                sl_percent=5.0,
                binance_api_key=encrypt_secret("mock_api_key_12345"),
                binance_api_secret=encrypt_secret("mock_api_secret_67890")
            )

            # Mock Telegram buy notifier
            notifications = []
            async def mock_buy_notifier(user_id, data):
                notifications.append(("BUY", user_id, data))

            trade_dispatcher.set_telegram_buy_notifier(mock_buy_notifier)

            # Mock binance order execution and price fetch
            mock_buy_res = {
                "success": True,
                "order_id": 11223344,
                "executed_qty": 0.0015,
                "usdt_spent": 100.0,
                "avg_price": 66666.67
            }

            with patch.object(binance_service, "place_spot_market_buy", return_value=mock_buy_res), \
                 patch.object(binance_service, "place_spot_market_sell", return_value={"success": True, "order_id": 998877, "avg_price": 70000.0}), \
                 patch.object(binance_service, "get_symbol_price", return_value=70000.0):

                print("Triggering real Upbit listing execution for BTC...")
                await trade_dispatcher.handle_listing(
                    raw_title="[거래] KRW, BTC 마켓 신규 디지털 자산 추가 (BTC)",
                    source="CapoStreamSim",
                    coin="BTC"
                )

                # Verify notification was sent for our test user
                user_notifs = [n for n in notifications if n[1] == test_uid]
                self.assertEqual(len(user_notifs), 1)
                event_type, uid, buy_data = user_notifs[0]
                self.assertEqual(event_type, "BUY")
                self.assertEqual(uid, test_uid)
                self.assertEqual(buy_data["symbol"], "BTCUSDT")
                trade_id = buy_data["trade_id"]
                print(f"Real-money order opened: Trade #{trade_id} at price ${buy_data['buy_price']}")

                # Verify trade recorded in DB
                trade = await get_open_trade_by_id(trade_id)
                self.assertIsNotNone(trade)
                self.assertEqual(trade["status"], "OPEN")

                # Test Panic Sell
                user = {
                    "telegram_id": test_uid,
                    "binance_api_key": encrypt_secret("mock_api_key_12345"),
                    "binance_api_secret": encrypt_secret("mock_api_secret_67890")
                }
                print("Testing emergency panic sell execution...")
                panic_res = await position_tracker.panic_sell_manual(trade_id, user)
                self.assertTrue(panic_res["success"])
                print(f"Panic sell success! PnL: {panic_res.get('pnl_percent'):.2f}%")

                # Verify closed trade in DB
                closed_trade = await get_open_trade_by_id(trade_id)
                self.assertEqual(closed_trade["status"], "CLOSED")
                self.assertEqual(closed_trade["exit_reason"], "MANUAL_PANIC_SELL")

            await binance_service.close()

        asyncio.run(run_pipeline())

if __name__ == "__main__":
    unittest.main()

