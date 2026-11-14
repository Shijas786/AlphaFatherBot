import re
import json
import asyncio
import logging
from typing import Optional, List, Callable, Set
import aiohttp
import config

logger = logging.getLogger(__name__)

EXCLUDED_WORDS = {
    "KRW", "BTC", "USDT", "ETH", "NOTICE", "EVENT", "AIRDROP", "MARKET", "UPBIT",
    "DEPOSIT", "WITHDRAWAL", "MAINTENANCE", "UPDATE", "TRADE", "API", "STAKING"
}

def is_upbit_listing_title(title: str) -> bool:
    """
    Strictly verify if an Upbit notice title is an actual new listing announcement.
    Rejects deposit/withdrawal suspensions, network upgrades, airdrops, delistings, and routine maintenance.
    """
    if not title:
        return False

    title_lower = title.lower()

    # 1. Non-listing / Maintenance / Suspension negative filters (STRICT DROP)
    negative_keywords = [
        "입출금",          # Deposit/Withdrawal
        "중단",            # Suspension / halt
        "재개",            # Resume
        "점검",            # Maintenance
        "업그레이드",       # Network upgrade
        "하드포크",         # Hard fork
        "에어드랍",         # Airdrop
        "지급",            # Distribution / payout
        "스냅샷",          # Snapshot
        "유의",            # Warning / Caution
        "종료",            # Delist / Termination
        "제거",            # Removal
        "변경",            # Change / Modification
        "안내사항",        # General notice
        "이벤트",          # Event
        "수수료",          # Fee
        "delist", "warning", "caution", "suspension", "maintenance", "upgrade", "halt", "resume", "airdrop"
    ]

    if any(k in title_lower for k in negative_keywords):
        return False

    # 2. Positive listing keywords (MUST CONTAIN AT LEAST ONE)
    positive_listing_keywords = [
        "신규 거래지원",    # New trading support
        "거래지원 안내",    # Trading support notice (e.g. 신규 거래지원 안내)
        "디지털 자산 추가",  # Digital asset addition
        "마켓 추가",        # Market addition
        "신규 상장",        # New listing
        "신규 마켓",        # New market
        "[거래]",          # [Trade] section
        "거래 지원",        # Trading support (with space)
        "listing", "added to", "new digital asset"
    ]

    return any(k in title_lower for k in positive_listing_keywords)

def parse_upbit_title(title: str) -> Optional[List[str]]:
    """
    Extract token tickers from Upbit listing announcement title.
    Only extracts if the title is a verified new listing announcement!
    Examples:
      - "[거래] KRW, BTC 마켓 디지털 자산 추가 (TIA)" -> ["TIA"]
      - "[거래] KRW 마켓 디지털 자산 추가 안내 (DRIFT, ZERO)" -> ["DRIFT", "ZERO"]
      - "생텀(SANC) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)" -> ["SANC"]
      - "[Trade] New Digital Asset (RENDER) Added to KRW Market" -> ["RENDER"]
    """
    if not title or not is_upbit_listing_title(title):
        return None

    # Match tokens inside parentheses: e.g. (TIA), (DRIFT, ZERO), 생텀(SANC)
    paren_matches = re.findall(r"\(([^)]+)\)", title)
    found_symbols = []

    for match in paren_matches:
        # Split by comma or slash
        parts = re.split(r"[,/ ]+", match)
        for part in parts:
            clean = part.strip().upper()
            if clean and clean not in EXCLUDED_WORDS and re.match(r"^[A-Z0-9]{2,10}$", clean):
                found_symbols.append(clean)

    # Fallback regex if no parentheses: e.g., "신규 디지털 자산 TIA 추가"
    if not found_symbols:
        fallback = re.findall(r"\b([A-Z0-9]{2,8})\b", title)
        for token in fallback:
            token = token.upper()
            if token not in EXCLUDED_WORDS and len(token) >= 2:
                found_symbols.append(token)

    return list(dict.fromkeys(found_symbols)) if found_symbols else None


class TreeNewsListener:
    def __init__(self, on_listing_detected: Callable[[str, str, str], None]):
        """
        :param on_listing_detected: Callback function (raw_title, source, coin_symbol)
        """
        self.on_listing_detected = on_listing_detected
        self.running = False
        self.processed_ids: Set[str] = set()
        self.processed_titles: Set[str] = set()

    async def start(self):
        """Connect to Tree News WebSocket with auto-reconnection."""
        self.running = True
        logger.info(f"Connecting to Tree News WebSocket at {config.TREE_NEWS_WS_URL}...")

        while self.running:
            try:
                headers = {}
                if config.TREE_NEWS_API_KEY:
                    headers["Authorization"] = f"Bearer {config.TREE_NEWS_API_KEY}"

                timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(config.TREE_NEWS_WS_URL, headers=headers) as ws:
                        logger.info("Successfully connected to Tree News WebSocket stream!")
                        
                        async for msg in ws:
                            if not self.running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_message(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                logger.warning(f"Tree News WebSocket closed or errored: {msg}")
                                break

            except Exception as e:
                logger.error(f"Tree News WebSocket connection error: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3)

    async def _handle_message(self, raw_data: str):
        """Process incoming Tree News message."""
        try:
            data = json.loads(raw_data)
        except Exception:
            return

        news_id = str(data.get("_id", data.get("id", "")))
        title = data.get("title", "")
        source = data.get("source", "")

        # Check duplicate
        if news_id and news_id in self.processed_ids:
            return
        if title and title in self.processed_titles:
            return

        if news_id:
            self.processed_ids.add(news_id)
        if title:
            self.processed_titles.add(title)

        # Check if source is Upbit or title has Upbit tags
        is_upbit = (
            "upbit" in source.lower()
            or "[upbit]" in title.lower()
            or "업비트" in title
            or "[거래]" in title
        )

        if not is_upbit:
            return

        # CRITICAL FILTER: Must be a verified new listing announcement!
        # Rejects deposit/withdrawal suspensions (e.g. KAVA, OSMO), network upgrades, delistings, etc.
        if not is_upbit_listing_title(title):
            logger.info(f"Skipping non-listing Upbit notice: '{title}'")
            return

        logger.info(f"VERIFIED Upbit listing announcement received: '{title}' (Source: {source})")

        # 1. Parse title directly using our strict listing regex
        symbols = parse_upbit_title(title)

        # 2. Fallback to suggestions ONLY if verified listing didn't extract symbols from title
        if not symbols and "suggestions" in data and isinstance(data["suggestions"], list):
            for sug in data["suggestions"]:
                coin = sug.get("coin", "").upper()
                if coin and coin not in EXCLUDED_WORDS:
                    symbols.append(coin)

        if symbols:
            for symbol in symbols:
                logger.info(f"🎯 CONFIRMED NEW LISTING: {symbol} from Upbit Announcement!")
                asyncio.create_task(self._trigger_callback(title, "CapoStream", symbol))

    async def _trigger_callback(self, title: str, source: str, symbol: str):
        try:
            if asyncio.iscoroutinefunction(self.on_listing_detected):
                await self.on_listing_detected(title, source, symbol)
            else:
                self.on_listing_detected(title, source, symbol)
        except Exception as e:
            logger.error(f"Error executing listing callback for {symbol}: {e}")

    def stop(self):
        self.running = False

