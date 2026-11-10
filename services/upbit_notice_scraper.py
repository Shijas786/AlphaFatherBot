import asyncio
import logging
from typing import Callable, Set, Optional
import aiohttp
from services.tree_news_listener import parse_upbit_title

logger = logging.getLogger(__name__)

UPBIT_NOTICES_URL = "https://api-manager.upbit.com/api/v1/notices?page=1&per_page=5&thread_name=general"

class UpbitNoticeScraper:
    """
    Direct redundant fallback listener querying Upbit's official notice API.
    Ensures zero missed listings even if Tree News WebSocket drops.
    """
    def __init__(self, on_listing_detected: Callable[[str, str, str], None], poll_interval: float = 1.5):
        self.on_listing_detected = on_listing_detected
        self.poll_interval = poll_interval
        self.running = False
        self.seen_notice_ids: Set[int] = set()
        self.initial_loaded = False

    async def start(self):
        self.running = True
        logger.info(f"Starting direct Upbit Notice Poller (interval: {self.poll_interval}s)...")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        while self.running:
            try:
                timeout = aiohttp.ClientTimeout(total=4)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(UPBIT_NOTICES_URL, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            notice_list = data.get("data", {}).get("list", [])
                            await self._process_notices(notice_list)
            except Exception as e:
                logger.debug(f"Upbit poller notice check error: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _process_notices(self, notices: list):
        if not self.initial_loaded:
            # First run: seed existing notice IDs so we don't trigger on old news
            for n in notices:
                self.seen_notice_ids.add(n.get("id"))
            self.initial_loaded = True
            logger.info(f"Upbit poller seeded with {len(self.seen_notice_ids)} existing notices.")
            return

        for notice in notices:
            nid = notice.get("id")
            title = notice.get("title", "")
            if nid in self.seen_notice_ids:
                continue

            self.seen_notice_ids.add(nid)
            logger.info(f"Upbit Direct Notice detected: {title}")

            symbols = parse_upbit_title(title)
            if symbols:
                for symbol in symbols:
                    logger.info(f"TARGET COIN FOUND (Direct Upbit): {symbol}")
                    asyncio.create_task(self._trigger_callback(title, "UpbitDirect", symbol))

    async def _trigger_callback(self, title: str, source: str, symbol: str):
        try:
            if asyncio.iscoroutinefunction(self.on_listing_detected):
                await self.on_listing_detected(title, source, symbol)
            else:
                self.on_listing_detected(title, source, symbol)
        except Exception as e:
            logger.error(f"Error in direct Upbit notice callback: {e}")

    def stop(self):
        self.running = False

