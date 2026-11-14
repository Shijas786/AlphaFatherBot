import asyncio
import os
import random
import unittest
from services.tree_news_listener import parse_upbit_title
from database.encryption import encrypt_secret, decrypt_secret
from database.db import init_db, create_or_update_user, update_user_fields, get_user, record_trade, close_trade, get_user_trades
from services.symbol_cache import symbol_cache

class TestUpbitSniper(unittest.TestCase):
    def test_regex_parsing(self):
        cases = [
            ("[거래] KRW, BTC 마켓 디지털 자산 추가 (TIA)", ["TIA"]),
            ("[거래] KRW 마켓 디지털 자산 추가 안내 (DRIFT, ZERO)", ["DRIFT", "ZERO"]),
            ("[Trade] New Digital Asset (RENDER) Added to KRW Market", ["RENDER"]),
            ("생텀(SANC) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)", ["SANC"]),
            ("카바(KAVA) 입출금 일시 중단 안내", None),  # Deposit suspension, NOT a listing!
            ("오스모시스(OSMO) 입출금 일시 중단 안내", None),  # Deposit suspension, NOT a listing!
            ("폴리곤에코시스템토큰(POL) 스테이킹 회원 대상 카타나(KAT) 에어드랍 지급 안내", None),  # Airdrop, NOT a listing!
            ("만트라(MANTRA) 거래지원 종료 안내 (12/14 15:00)", None),  # Delisting, NOT a listing!
            ("[안내] 입출금 일시 중단 안내", None),  # Not a listing
            ("[유의] 거래지원 종료 안내 (XYZ)", None),  # Delisting, should be ignored
        ]
        for title, expected in cases:
            res = parse_upbit_title(title)
            self.assertEqual(res, expected, f"Failed on title: {title}")

    def test_encryption(self):
        secret = "secret_binance_api_key_1234567890"
        encrypted = encrypt_secret(secret)
        self.assertNotEqual(secret, encrypted)
        decrypted = decrypt_secret(encrypted)
        self.assertEqual(secret, decrypted)

    def test_async_database_and_cache(self):
        async def run_async_tests():
            await init_db()
            test_uid = random.randint(1000000, 9999999)
            user = await create_or_update_user(test_uid, "testuser", "Test")
            self.assertEqual(user["telegram_id"], test_uid)

            await update_user_fields(test_uid, order_amount_usdt=75.0, trade_mode="futures")
            updated = await get_user(test_uid)
            self.assertEqual(updated["order_amount_usdt"], 75.0)
            self.assertEqual(updated["trade_mode"], "futures")

            trade_id = await record_trade(
                user_id=test_uid,
                symbol="TIAUSDT",
                trade_mode="spot",
                side="BUY",
                order_id="TEST_101",
                buy_price=5.0,
                quantity=10.0,
                usdt_spent=50.0
            )
            self.assertGreater(trade_id, 0)

            await close_trade(
                trade_id=trade_id,
                sell_price=6.0,
                sell_order_id="TEST_SELL_101",
                pnl_percent=20.0,
                pnl_usdt=10.0,
                exit_reason="TAKE_PROFIT"
            )

            trades = await get_user_trades(test_uid)
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["exit_reason"], "TAKE_PROFIT")
            self.assertEqual(trades[0]["pnl_percent"], 20.0)

            # Test symbol cache against live Binance public endpoint
            print("Testing Binance Symbol Cache fetch...")
            await symbol_cache.initialize()
            res = symbol_cache.resolve_symbol("BTC")
            self.assertIsNotNone(res)
            self.assertEqual(res["symbol"], "BTCUSDT")
            print(f"Symbol cache verification successful: Resolved BTC -> {res['symbol']}")

            # Test Group Registration and Alerts
            from database.db import register_group, deactivate_group, get_active_groups, get_group_stats
            test_group_id = -1009988776655
            await register_group(test_group_id, "Crypto Alpha Syndicate", "supergroup", 123456)
            active_groups = await get_active_groups()
            self.assertTrue(any(g["chat_id"] == test_group_id for g in active_groups))
            stats = await get_group_stats()
            self.assertGreaterEqual(stats["active_groups"], 1)

            # Test Group Deactivation
            await deactivate_group(test_group_id)
            active_after = await get_active_groups()
            self.assertFalse(any(g["chat_id"] == test_group_id for g in active_after))

        asyncio.run(run_async_tests())

if __name__ == "__main__":
    unittest.main()
