import asyncio
import unittest
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web
from webapp.server import create_webapp
from database.db import init_db, create_or_update_user

class TestWebApp(AioHTTPTestCase):
    async def get_application(self):
        await init_db()
        await create_or_update_user(123456789, "tester", "Test User")
        return create_webapp()

    @unittest_run_loop
    async def test_serve_html(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("CAPO", text)

    @unittest_run_loop
    async def test_api_user_endpoint(self):
        headers = {"Authorization": "Bearer test_user_123456789"}
        resp = await self.client.get("/api/user", headers=headers)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["user"]["telegram_id"], 123456789)

    @unittest_run_loop
    async def test_api_update_settings(self):
        headers = {"Authorization": "Bearer test_user_123456789"}
        payload = {"is_active": 1, "order_amount_usdt": 120.0, "tp_percent": 18.0, "max_hold_seconds": 0}
        resp = await self.client.post("/api/user/settings", headers=headers, json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])

        # Check updated
        user_resp = await self.client.get("/api/user", headers=headers)
        user_data = await user_resp.json()
        self.assertTrue(user_data["user"]["is_active"])
        self.assertEqual(user_data["user"]["order_amount_usdt"], 120.0)
        self.assertEqual(user_data["user"]["tp_percent"], 18.0)

    @unittest_run_loop
    async def test_api_update_settings_rejects_invalid_values(self):
        headers = {"Authorization": "Bearer test_user_123456789"}
        await self.client.post("/api/user/settings", headers=headers, json={"order_amount_usdt": 75.0})
        for payload in (
            {"order_amount_usdt": -50},
            {"order_amount_usdt": "abc"},
            {"trade_mode": "margin"},
            {"snipe_venue": "everywhere"},
            {"futures_leverage": 0},
            {"sl_percent": 250},
            {"is_active": 5},
        ):
            resp = await self.client.post("/api/user/settings", headers=headers, json=payload)
            self.assertEqual(resp.status, 400, payload)

        user_data = await (await self.client.get("/api/user", headers=headers)).json()
        self.assertEqual(user_data["user"]["order_amount_usdt"], 75.0)

    @unittest_run_loop
    async def test_wallet_and_panic_endpoints_reject_bad_numbers(self):
        headers = {"Authorization": "Bearer test_user_123456789"}
        for path, payload in (
            ("/api/wallet/send", {"recipient": "abc", "amount": "lots"}),
            ("/api/wallet/send", {"recipient": "abc", "amount": "nan"}),
            ("/api/wallet/sell", {"mint": "abc", "percentage": "half"}),
            ("/api/wallet/sell", {"mint": "abc", "percentage": 5}),
            ("/api/wallet/sell", {"mint": "abc", "percentage": -1}),
            ("/api/trades/panic-sell", {"trade_id": "abc"}),
        ):
            resp = await self.client.post(path, headers=headers, json=payload)
            self.assertEqual(resp.status, 400, (path, payload))

    @unittest_run_loop
    async def test_wallet_send_uses_requested_evm_network(self):
        from unittest import mock

        headers = {"Authorization": "Bearer test_user_123456789"}
        user = {"telegram_id": 123456789, "encrypted_evm_private_key": "enc"}
        send = mock.AsyncMock(return_value={"success": True})
        with mock.patch("webapp.routes.get_user", mock.AsyncMock(return_value=user)), \
                mock.patch("webapp.routes.decrypt_secret", return_value="ab" * 32), \
                mock.patch("services.evm_wallet.send_evm_native", send):
            for chain, network in (("evm", "base"), ("base", "base"), ("ethereum", "ethereum"), ("bsc", "bsc")):
                resp = await self.client.post(
                    "/api/wallet/send", headers=headers,
                    json={"chain": chain, "recipient": "0xabc", "amount": 0.1},
                )
                self.assertEqual(resp.status, 200)
                self.assertEqual(send.call_args.kwargs["network"], network, chain)

    @unittest_run_loop
    async def test_api_listings_endpoint(self):
        resp = await self.client.get("/api/listings")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertIn("listings", data)

    @unittest_run_loop
    async def test_api_status_endpoint(self):
        for path in ("/api/status", "/api/ip"):
            resp = await self.client.get(path)
            self.assertEqual(resp.status, 401, path)

        headers = {"Authorization": "Bearer test_user_123456789"}
        resp = await self.client.get("/api/status", headers=headers)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertIn("active_groups_count", data)
        self.assertIn("outbound_ip", data)

class TestInitDataAuth(unittest.TestCase):
    def test_test_user_shortcut_rejected_when_bot_token_set(self):
        import config
        from unittest import mock
        from webapp.auth import validate_init_data

        with mock.patch.object(config, "TELEGRAM_BOT_TOKEN", "123:abc"):
            self.assertIsNone(validate_init_data("test_user_123456789"))
        with mock.patch.object(config, "TELEGRAM_BOT_TOKEN", ""):
            self.assertEqual(validate_init_data("test_user_123456789")["id"], 123456789)
            self.assertIsNone(validate_init_data("test_user_abc"))

    def test_signed_init_data_expires(self):
        import hashlib, hmac, json, time, urllib.parse
        import config
        from unittest import mock
        from webapp.auth import validate_init_data, MAX_INIT_DATA_AGE_SECONDS

        token = "123:abc"

        def signed(auth_date):
            fields = {"auth_date": str(auth_date), "user": json.dumps({"id": 42})}
            check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
            secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
            fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
            return urllib.parse.urlencode(fields)

        now = int(time.time())
        with mock.patch.object(config, "TELEGRAM_BOT_TOKEN", token):
            self.assertEqual(validate_init_data(signed(now))["id"], 42)
            self.assertIsNone(validate_init_data(signed(now - MAX_INIT_DATA_AGE_SECONDS - 60)))
            self.assertIsNone(validate_init_data(signed(now) + "0"))

if __name__ == "__main__":
    unittest.main()

