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
        self.assertIn("UPBIT SNIPER", text)

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
        payload = {"is_active": 1, "order_amount_usdt": 120.0, "tp_percent": 18.0}
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
    async def test_api_listings_endpoint(self):
        resp = await self.client.get("/api/listings")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertIn("listings", data)

if __name__ == "__main__":
    unittest.main()

