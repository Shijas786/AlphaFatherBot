import asyncio
import logging
import aiohttp
from typing import Dict, Any, Optional
import config

logger = logging.getLogger(__name__)

class SymbolCache:
    def __init__(self):
        self.spot_symbols: Dict[str, Dict[str, Any]] = {}      # 'BTCUSDT' -> info
        self.futures_symbols: Dict[str, Dict[str, Any]] = {}   # 'BTCUSDT' -> info
        self.spot_by_base: Dict[str, str] = {}                 # 'BTC' -> 'BTCUSDT'
        self.futures_by_base: Dict[str, str] = {}              # 'BTC' -> 'BTCUSDT'
        self.is_loaded = False
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Fetch exchangeInfo for Spot and Futures at startup."""
        await self.refresh_cache()

    async def refresh_cache(self):
        """Fetch Binance Spot & Futures exchange info and populate RAM cache."""
        async with self._lock:
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    # Fetch Spot & Futures concurrently
                    spot_task = session.get(f"{config.BINANCE_SPOT_BASE_URL}/api/v3/exchangeInfo")
                    futures_task = session.get(f"{config.BINANCE_FUTURES_BASE_URL}/fapi/v1/exchangeInfo")
                    
                    spot_res, futures_res = await asyncio.gather(spot_task, futures_task, return_exceptions=True)

                    if not isinstance(spot_res, Exception) and spot_res.status == 200:
                        data = await spot_res.json()
                        self._parse_spot(data)
                        logger.info(f"Loaded {len(self.spot_symbols)} Binance Spot USDT pairs into RAM.")
                    else:
                        logger.error(f"Failed to fetch Binance Spot exchange info: {spot_res}")

                    if not isinstance(futures_res, Exception) and futures_res.status == 200:
                        data = await futures_res.json()
                        self._parse_futures(data)
                        logger.info(f"Loaded {len(self.futures_symbols)} Binance Futures USDT pairs into RAM.")
                    else:
                        logger.error(f"Failed to fetch Binance Futures exchange info: {futures_res}")

                    self.is_loaded = True
            except Exception as e:
                logger.error(f"Error refreshing Binance symbol cache: {e}")

    def _parse_spot(self, data: dict):
        new_spot = {}
        new_by_base = {}
        for s in data.get("symbols", []):
            if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                symbol = s["symbol"]
                base = s["baseAsset"].upper()
                
                step_size = "0.000001"
                min_qty = "0.000001"
                min_notional = 5.0
                tick_size = "0.000001"

                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        step_size = f.get("stepSize", step_size)
                        min_qty = f.get("minQty", min_qty)
                    elif f["filterType"] in ("NOTIONAL", "MIN_NOTIONAL"):
                        min_notional = float(f.get("minNotional", 5.0))
                    elif f["filterType"] == "PRICE_FILTER":
                        tick_size = f.get("tickSize", tick_size)

                new_spot[symbol] = {
                    "symbol": symbol,
                    "baseAsset": base,
                    "quoteAsset": "USDT",
                    "step_size": float(step_size),
                    "min_qty": float(min_qty),
                    "min_notional": min_notional,
                    "tick_size": float(tick_size)
                }
                new_by_base[base] = symbol

        self.spot_symbols = new_spot
        self.spot_by_base = new_by_base

    def _parse_futures(self, data: dict):
        new_futures = {}
        new_by_base = {}
        for s in data.get("symbols", []):
            if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL":
                symbol = s["symbol"]
                base = s["baseAsset"].upper()
                
                step_size = "0.001"
                min_qty = "0.001"
                min_notional = 5.0
                tick_size = "0.001"

                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        step_size = f.get("stepSize", step_size)
                        min_qty = f.get("minQty", min_qty)
                    elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                        min_notional = float(f.get("notional", 5.0))
                    elif f["filterType"] == "PRICE_FILTER":
                        tick_size = f.get("tickSize", tick_size)

                new_futures[symbol] = {
                    "symbol": symbol,
                    "baseAsset": base,
                    "quoteAsset": "USDT",
                    "step_size": float(step_size),
                    "min_qty": float(min_qty),
                    "min_notional": min_notional,
                    "tick_size": float(tick_size)
                }
                new_by_base[base] = symbol

        self.futures_symbols = new_futures
        self.futures_by_base = new_by_base

    def resolve_symbol(self, coin: str, trade_mode: str = "spot") -> Optional[Dict[str, Any]]:
        """
        Instant 0ms RAM lookup of whether coin is tradable on Binance.
        Accepts 'TIA', 'TIAUSDT', etc.
        Returns symbol info dict or None.
        """
        coin_clean = coin.upper().strip()
        if coin_clean.endswith("USDT"):
            symbol = coin_clean
        else:
            symbol = f"{coin_clean}USDT"

        if trade_mode == "futures":
            if symbol in self.futures_symbols:
                return self.futures_symbols[symbol]
            # Fallback to Spot if Futures not available
            if symbol in self.spot_symbols:
                return self.spot_symbols[symbol]
        else:
            if symbol in self.spot_symbols:
                return self.spot_symbols[symbol]
            # Fallback to Futures if Spot not available
            if symbol in self.futures_symbols:
                return self.futures_symbols[symbol]
        
        return None

# Singleton instance
symbol_cache = SymbolCache()

