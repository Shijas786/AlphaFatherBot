"""
Upbit Contract Extractor
========================
Extracts blockchain contract addresses and network info from Upbit listing announcements.

Strategy (in order):
1. Try Upbit api-manager notice-detail endpoint (UUID-based)
2. Try fetching the notice page as HTML and extract from og:description / JSON-LD
3. Fallback: DexScreener search by ticker + Jupiter strict-list verification
"""

import re
import logging
import asyncio
from typing import Optional, Dict, Any
import aiohttp

logger = logging.getLogger(__name__)

# ─── SOL address: 32-44 Base58 chars (no 0, O, I, l)
_SOLANA_RE = re.compile(r'\b([1-9A-HJ-NP-Za-km-z]{32,44})\b')
# ─── EVM address: 0x + 40 hex chars
_EVM_RE = re.compile(r'\b(0x[a-fA-F0-9]{40})\b')

# Map Korean / English network names → canonical chain id
_NETWORK_MAP = {
    "솔라나": "solana", "solana": "solana",
    "이더리움": "ethereum", "ethereum": "ethereum", "eth": "ethereum",
    "베이스": "base", "base": "base",
    "아비트럼": "arbitrum", "arbitrum": "arbitrum", "arb": "arbitrum",
    "비엔비체인": "bsc", "바이낸스": "bsc", "bsc": "bsc", "bnb": "bsc",
    "폴리곤": "polygon", "polygon": "polygon", "matic": "polygon",
    "비트코인": "bitcoin",  # No DEX — will be skipped by swapper
    "수이": "sui", "sui": "sui",
    "아발란체": "avalanche", "avalanche": "avalanche", "avax": "avalanche",
}

# Known non-contract Base58 strings to ignore (Solana program IDs, etc.)
_SOLANA_IGNORE = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # SPL Token program
    "11111111111111111111111111111111",               # System program
    "So11111111111111111111111111111111111111112",    # Wrapped SOL
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe8bXh", # ATA program
}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.9",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://www.upbit.com/",
}


def _extract_network_from_text(text: str) -> Optional[str]:
    """Scan Korean/English text for a network name keyword."""
    text_lower = text.lower()
    for keyword, chain in _NETWORK_MAP.items():
        if keyword in text_lower:
            return chain
    return None


def _extract_contracts_from_text(text: str) -> Dict[str, list]:
    """Return {'solana': [...], 'evm': [...]} addresses found in text."""
    sol = [m for m in _SOLANA_RE.findall(text) if m not in _SOLANA_IGNORE]
    evm = _EVM_RE.findall(text)
    return {"solana": sol, "evm": evm}


def _extract_uuid_from_url(url: str) -> Optional[str]:
    """Pull the notice UUID from an Upbit notice URL."""
    m = re.search(
        r'[?&]id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
        url, re.IGNORECASE
    )
    return m.group(1) if m else None


async def _try_api_manager(session: aiohttp.ClientSession, uuid: str) -> Optional[str]:
    """
    Try the undocumented Upbit API manager notice-detail endpoint.
    Returns the article body text on success, None otherwise.
    """
    url = f"https://api-manager.upbit.com/api/v1/notices/{uuid}"
    try:
        async with session.get(url, headers=_BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=5)) as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                body = (
                    data.get("data", {}).get("body", "")
                    or data.get("body", "")
                    or data.get("content", "")
                )
                if body:
                    logger.info(f"[ContractExtractor] Got body from api-manager ({len(body)} chars)")
                    return body
    except Exception as e:
        logger.debug(f"[ContractExtractor] api-manager fetch failed: {e}")
    return None


async def _try_upbit_html(session: aiohttp.ClientSession, uuid: str) -> Optional[str]:
    """
    Fetch the Upbit notice share page and extract visible text from og:description
    or any script/data blocks.
    """
    url = f"https://www.upbit.com/service_center/notice?id={uuid}&view=share"
    try:
        async with session.get(url, headers=_BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status == 200:
                html = await r.text()
                # og:description often has the first few lines
                m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html)
                if m:
                    snippet = m.group(1)
                    logger.info(f"[ContractExtractor] Got og:description snippet: {snippet[:120]}")
                    return snippet
                # Try extracting from any JSON blob in the page
                json_m = re.search(r'"body"\s*:\s*"((?:[^"\\]|\\.)+)"', html)
                if json_m:
                    return json_m.group(1).replace('\\n', '\n').replace('\\"', '"')
    except Exception as e:
        logger.debug(f"[ContractExtractor] HTML fetch failed: {e}")
    return None


async def _try_dexscreener_fallback(session: aiohttp.ClientSession, symbol: str) -> Optional[Dict[str, Any]]:
    """
    Last resort: search DexScreener for the token and pick the highest-liquidity pool
    that is on a supported chain.
    """
    url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status == 200:
                data = await r.json()
                pairs = data.get("pairs") or []
                # Filter to supported chains with real liquidity
                SUPPORTED = {"solana", "ethereum", "base", "bsc", "arbitrum", "polygon"}
                pairs = [
                    p for p in pairs
                    if p.get("chainId", "").lower() in SUPPORTED
                    and float(p.get("liquidity", {}).get("usd", 0) or 0) > 10_000
                ]
                if not pairs:
                    return None
                # Sort by liquidity descending
                pairs.sort(key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0), reverse=True)
                best = pairs[0]
                chain = best.get("chainId", "").lower()
                contract = best.get("baseToken", {}).get("address", "")
                liq = float(best.get("liquidity", {}).get("usd", 0) or 0)
                if contract:
                    logger.info(f"[ContractExtractor] DexScreener fallback: {symbol} -> {chain} {contract} (liq ${liq:,.0f})")
                    return {"network": chain, "contract": contract, "source": "dexscreener_fallback", "liquidity_usd": liq}
    except Exception as e:
        logger.debug(f"[ContractExtractor] DexScreener fallback error: {e}")
    return None


async def extract_contract(
    symbol: str,
    notice_url: Optional[str] = None,
    notice_body_text: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Main entry point. Returns a dict like:
      {
        "network":  "solana" | "ethereum" | "base" | "bsc" | "arbitrum",
        "contract": "CLoUDKc4...",
        "source":   "api_manager" | "html_snippet" | "body_text" | "dexscreener_fallback",
        "symbol":   "SANC"
      }
    Returns None if no contract could be found.
    """
    uuid = _extract_uuid_from_url(notice_url) if notice_url else None

    async with aiohttp.ClientSession() as session:

        # ── Try 1: body text already provided (e.g. from Tree News raw message)
        if notice_body_text:
            logger.info("[ContractExtractor] Scanning provided body text...")
            result = _parse_body_for_contract(notice_body_text, symbol, source="body_text")
            if result:
                return result

        # ── Try 2: Upbit API Manager (undocumented)
        if uuid:
            body = await _try_api_manager(session, uuid)
            if body:
                result = _parse_body_for_contract(body, symbol, source="api_manager")
                if result:
                    return result

        # ── Try 3: Upbit HTML share page
        if uuid:
            snippet = await _try_upbit_html(session, uuid)
            if snippet:
                result = _parse_body_for_contract(snippet, symbol, source="html_snippet")
                if result:
                    return result

        # ── Try 4: DexScreener search fallback
        logger.warning(f"[ContractExtractor] Primary sources failed for {symbol} — trying DexScreener fallback...")
        result = await _try_dexscreener_fallback(session, symbol)
        if result:
            result["symbol"] = symbol
            return result

    logger.error(f"[ContractExtractor] Could not find contract for {symbol}")
    return None


def _parse_body_for_contract(text: str, symbol: str, source: str) -> Optional[Dict[str, Any]]:
    """
    Given a chunk of notice text, extract network + contract address.
    Priority: Solana > EVM (by mention of network keyword near contract).
    """
    contracts = _extract_contracts_from_text(text)
    network = _extract_network_from_text(text)

    if network == "solana" and contracts["solana"]:
        contract = contracts["solana"][0]
        logger.info(f"[ContractExtractor] ✅ Solana contract found: {contract} (source: {source})")
        return {"network": "solana", "contract": contract, "symbol": symbol, "source": source}

    if network in ("ethereum", "base", "bsc", "arbitrum", "polygon") and contracts["evm"]:
        contract = contracts["evm"][0]
        logger.info(f"[ContractExtractor] ✅ EVM contract found on {network}: {contract} (source: {source})")
        return {"network": network, "contract": contract, "symbol": symbol, "source": source}

    # If we found addresses but couldn't determine network, pick by address type
    if contracts["solana"]:
        contract = contracts["solana"][0]
        logger.info(f"[ContractExtractor] ✅ Solana address (network unknown): {contract}")
        return {"network": "solana", "contract": contract, "symbol": symbol, "source": source}

    if contracts["evm"] and network:
        contract = contracts["evm"][0]
        return {"network": network, "contract": contract, "symbol": symbol, "source": source}

    return None
