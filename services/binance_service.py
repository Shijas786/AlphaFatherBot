import time
import hmac
import hashlib
import math
import logging
from urllib.parse import urlencode
from typing import Dict, Any, Tuple, Optional
import aiohttp
import config

logger = logging.getLogger(__name__)

class BinanceService:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # High-performance TCP connector with persistent connection pool & keep-alive
            connector = aiohttp.TCPConnector(
                limit=100,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
                ssl=True
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=5, connect=2)
            )
        return self._session

    def _sign(self, secret: str, params: Dict[str, Any]) -> str:
        """Create HMAC-SHA256 signature for Binance API query."""
        query_string = urlencode(params)
        return hmac.new(
            secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    async def test_credentials(self, api_key: str, api_secret: str, check_futures: bool = False) -> Tuple[bool, str]:
        """Test API key validity and permissions."""
        session = await self.get_session()
        params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
        params["signature"] = self._sign(api_secret, params)
        headers = {"X-MBX-APIKEY": api_key}

        url = f"{config.BINANCE_FUTURES_BASE_URL}/fapi/v2/account" if check_futures else f"{config.BINANCE_SPOT_BASE_URL}/api/v3/account"

        try:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    return True, "API Key successfully validated!"
                else:
                    data = await resp.json()
                    msg = data.get("msg", "Failed to authenticate with Binance.")
                    return False, f"Binance error: {msg}"
        except Exception as e:
            logger.error(f"Error testing Binance credentials: {e}")
            return False, f"Connection error: {str(e)}"

    async def get_balance(self, api_key: str, api_secret: str, is_futures: bool = False) -> float:
        """Get available free USDT balance."""
        session = await self.get_session()
        params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
        params["signature"] = self._sign(api_secret, params)
        headers = {"X-MBX-APIKEY": api_key}

        try:
            if is_futures:
                url = f"{config.BINANCE_FUTURES_BASE_URL}/fapi/v2/balance"
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data:
                            if item.get("asset") == "USDT":
                                return float(item.get("availableBalance", 0.0))
            else:
                url = f"{config.BINANCE_SPOT_BASE_URL}/api/v3/account"
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("balances", []):
                            if item.get("asset") == "USDT":
                                return float(item.get("free", 0.0))
        except Exception as e:
            logger.error(f"Error fetching USDT balance: {e}")
        return 0.0

    async def get_symbol_price(self, symbol: str, is_futures: bool = False) -> float:
        """Fetch current ticker price."""
        session = await self.get_session()
        url = (
            f"{config.BINANCE_FUTURES_BASE_URL}/fapi/v1/ticker/price?symbol={symbol}"
            if is_futures
            else f"{config.BINANCE_SPOT_BASE_URL}/api/v3/ticker/price?symbol={symbol}"
        )
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data.get("price", 0.0))
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
        return 0.0

    async def place_spot_market_buy(
        self,
        api_key: str,
        api_secret: str,
        symbol: str,
        usdt_amount: float
    ) -> Dict[str, Any]:
        """
        Instant Market Buy on Binance Spot using quoteOrderQty (USDT amount).
        Ultra-fast execution: no prior price calculation needed!
        """
        session = await self.get_session()
        params = {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{usdt_amount:.2f}",
            "recvWindow": 5000,
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = self._sign(api_secret, params)
        headers = {"X-MBX-APIKEY": api_key}

        url = f"{config.BINANCE_SPOT_BASE_URL}/api/v3/order"
        start_time = time.time()
        try:
            async with session.post(url, data=params, headers=headers) as resp:
                latency_ms = int((time.time() - start_time) * 1000)
                data = await resp.json()
                if resp.status == 200:
                    # Calculate executed weighted average price
                    executed_qty = float(data.get("executedQty", 0.0))
                    cummulative_quote_qty = float(data.get("cummulativeQuoteQty", 0.0))
                    avg_price = (cummulative_quote_qty / executed_qty) if executed_qty > 0 else 0.0

                    return {
                        "success": True,
                        "order_id": str(data.get("orderId")),
                        "symbol": symbol,
                        "executed_qty": executed_qty,
                        "usdt_spent": cummulative_quote_qty,
                        "avg_price": avg_price,
                        "latency_ms": latency_ms,
                        "raw": data
                    }
                else:
                    return {
                        "success": False,
                        "error": data.get("msg", "Spot buy failed"),
                        "latency_ms": latency_ms
                    }
        except Exception as e:
            return {"success": False, "error": str(e), "latency_ms": int((time.time() - start_time) * 1000)}

    async def place_spot_market_sell(
        self,
        api_key: str,
        api_secret: str,
        symbol: str,
        quantity: float,
        step_size: float = 0.0001
    ) -> Dict[str, Any]:
        """Sell token on Spot at Market."""
        session = await self.get_session()
        # Round quantity down according to step_size
        precision = max(0, int(round(-math.log10(step_size)))) if step_size > 0 else 4
        fmt_qty = f"{math.floor(quantity * (10 ** precision)) / (10 ** precision):.{precision}f}"

        params = {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": fmt_qty,
            "recvWindow": 5000,
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = self._sign(api_secret, params)
        headers = {"X-MBX-APIKEY": api_key}

        url = f"{config.BINANCE_SPOT_BASE_URL}/api/v3/order"
        try:
            async with session.post(url, data=params, headers=headers) as resp:
                data = await resp.json()
                if resp.status == 200:
                    executed_qty = float(data.get("executedQty", 0.0))
                    cummulative_quote_qty = float(data.get("cummulativeQuoteQty", 0.0))
                    avg_price = (cummulative_quote_qty / executed_qty) if executed_qty > 0 else 0.0
                    return {
                        "success": True,
                        "order_id": str(data.get("orderId")),
                        "executed_qty": executed_qty,
                        "usdt_received": cummulative_quote_qty,
                        "avg_price": avg_price
                    }
                return {"success": False, "error": data.get("msg", "Spot sell failed")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def place_futures_market_buy(
        self,
        api_key: str,
        api_secret: str,
        symbol: str,
        usdt_amount: float,
        leverage: int = 3,
        step_size: float = 0.001
    ) -> Dict[str, Any]:
        """Place Market Long on Binance USDT-M Futures."""
        session = await self.get_session()
        headers = {"X-MBX-APIKEY": api_key}

        # 1. Set Leverage
        lev_params = {
            "symbol": symbol,
            "leverage": leverage,
            "recvWindow": 5000,
            "timestamp": int(time.time() * 1000)
        }
        lev_params["signature"] = self._sign(api_secret, lev_params)
        try:
            await session.post(f"{config.BINANCE_FUTURES_BASE_URL}/fapi/v1/leverage", data=lev_params, headers=headers)
        except Exception as e:
            logger.warning(f"Failed to set leverage for {symbol}: {e}")

        # 2. Get current price to calculate contract quantity
        price = await self.get_symbol_price(symbol, is_futures=True)
        if price <= 0:
            return {"success": False, "error": "Could not determine mark price for Futures."}

        total_position_value = usdt_amount * leverage
        raw_qty = total_position_value / price

        precision = max(0, int(round(-math.log10(step_size)))) if step_size > 0 else 3
        fmt_qty = f"{math.floor(raw_qty * (10 ** precision)) / (10 ** precision):.{precision}f}"

        # 3. Submit Market Order
        params = {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": fmt_qty,
            "recvWindow": 5000,
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = self._sign(api_secret, params)

        start_time = time.time()
        url = f"{config.BINANCE_FUTURES_BASE_URL}/fapi/v1/order"
        try:
            async with session.post(url, data=params, headers=headers) as resp:
                latency_ms = int((time.time() - start_time) * 1000)
                data = await resp.json()
                if resp.status == 200:
                    executed_qty = float(data.get("executedQty", fmt_qty))
                    avg_price = float(data.get("avgPrice", price))
                    if avg_price == 0:
                        avg_price = price
                    return {
                        "success": True,
                        "order_id": str(data.get("orderId")),
                        "symbol": symbol,
                        "executed_qty": executed_qty,
                        "usdt_spent": usdt_amount,
                        "avg_price": avg_price,
                        "latency_ms": latency_ms,
                        "raw": data
                    }
                else:
                    return {"success": False, "error": data.get("msg", "Futures buy failed"), "latency_ms": latency_ms}
        except Exception as e:
            return {"success": False, "error": str(e), "latency_ms": int((time.time() - start_time) * 1000)}

    async def place_futures_market_sell(
        self,
        api_key: str,
        api_secret: str,
        symbol: str,
        quantity: float,
        step_size: float = 0.001
    ) -> Dict[str, Any]:
        """Close Futures Long position using market order with reduceOnly."""
        session = await self.get_session()
        precision = max(0, int(round(-math.log10(step_size)))) if step_size > 0 else 3
        fmt_qty = f"{math.floor(quantity * (10 ** precision)) / (10 ** precision):.{precision}f}"

        params = {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": fmt_qty,
            "reduceOnly": "true",
            "recvWindow": 5000,
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = self._sign(api_secret, params)
        headers = {"X-MBX-APIKEY": api_key}

        url = f"{config.BINANCE_FUTURES_BASE_URL}/fapi/v1/order"
        try:
            async with session.post(url, data=params, headers=headers) as resp:
                data = await resp.json()
                if resp.status == 200:
                    avg_price = float(data.get("avgPrice", 0.0))
                    return {
                        "success": True,
                        "order_id": str(data.get("orderId")),
                        "avg_price": avg_price,
                        "executed_qty": float(data.get("executedQty", fmt_qty))
                    }
                return {"success": False, "error": data.get("msg", "Futures sell failed")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        """Close client session and connector."""
        if self._session and not self._session.closed:
            await self._session.close()

# Singleton instance
binance_service = BinanceService()
