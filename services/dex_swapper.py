"""
DEX Swapper — Jupiter v6 (Solana)
===================================
Executes token purchases on Solana via Jupiter Aggregator v6 API.

Flow:
  1. get_jupiter_quote()      — fetch best route & price impact
  2. build_jupiter_swap_tx()  — get serialized transaction from Jupiter
  3. sign_and_send_tx()       — sign with user's keypair & submit to Solana RPC
  4. execute_jupiter_swap()   — high-level wrapper used by trade_dispatcher

Security:
  - Private key is decrypted in-memory only during signing; never logged.
  - Minimum liquidity guard: skip if Jupiter returns no route.
  - Slippage default: 3% (300 bps). Configurable via SOLANA_SLIPPAGE_BPS env.
"""

import base64
import logging
import asyncio
import time
from typing import Optional, Dict, Any
import aiohttp
import config
from database.encryption import decrypt_secret
from services.solana_wallet import keypair_from_private_key, LAMPORTS_PER_SOL, DEFAULT_SOLANA_RPC

logger = logging.getLogger(__name__)

# ─── Jupiter v6 endpoints ─────────────────────────────────────────────────────
JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL  = "https://quote-api.jup.ag/v6/swap"
SOL_MINT          = "So11111111111111111111111111111111111111112"

# ─── DexScreener — for liquidity pre-check ────────────────────────────────────
DEXSCREENER_URL   = "https://api.dexscreener.com/latest/dex/tokens/"

# ─── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_SLIPPAGE_BPS   = getattr(config, "DEX_SLIPPAGE_BPS", 1500)  # 15% slippage buffer for listing pumps
MIN_LIQUIDITY_USD      = 3_000  # Low threshold

_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


async def get_jupiter_quote(
    output_mint: str,
    sol_amount: float,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
) -> Optional[Dict[str, Any]]:
    """
    Fetch the best Jupiter quote to swap SOL → {output_mint}.

    Args:
        output_mint:   Token mint address (e.g. SANC contract)
        sol_amount:    Amount of SOL to spend (e.g. 0.1)
        slippage_bps:  Slippage tolerance in basis points (default 300 = 3%)

    Returns:
        Jupiter quoteResponse dict on success, None if no route / error.
    """
    amount_lamports = int(sol_amount * LAMPORTS_PER_SOL)
    params = {
        "inputMint":   SOL_MINT,
        "outputMint":  output_mint,
        "amount":      amount_lamports,
        "slippageBps": slippage_bps,
        "onlyDirectRoutes": "false",
        "asLegacyTransaction": "false",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                JUPITER_QUOTE_URL,
                params=params,
                headers=_HEADERS,
                timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(f"[DEXSwapper] Jupiter quote {resp.status}: {text[:200]}")
                    return None
                quote = await resp.json()
                out_amount = int(quote.get("outAmount", 0))
                price_impact = float(quote.get("priceImpactPct", 0))
                logger.info(
                    f"[DEXSwapper] Quote: {sol_amount} SOL → {out_amount} tokens "
                    f"| priceImpact: {price_impact:.2f}% | slippage: {slippage_bps/100:.1f}%"
                )
                return quote
    except Exception as e:
        logger.error(f"[DEXSwapper] Jupiter quote error: {e}")
        return None


async def _check_dexscreener_liquidity(mint: str) -> float:
    """Return USD liquidity for the token; 0 if not found."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                DEXSCREENER_URL + mint,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return 0.0
                data = await resp.json()
                pairs = data.get("pairs") or []
                if not pairs:
                    return 0.0
                # Sum liquidity across all pairs for this token
                total = sum(
                    float(p.get("liquidity", {}).get("usd", 0) or 0)
                    for p in pairs
                    if (p.get("chainId") or "").lower() == "solana"
                )
                return total
    except Exception:
        return 0.0


async def _build_swap_transaction(
    quote_response: Dict[str, Any],
    user_public_key: str,
) -> Optional[str]:
    """
    Call Jupiter /swap to get a serialized, versioned transaction (base64).
    Returns base64 transaction string or None on failure.
    """
    payload = {
        "quoteResponse":        quote_response,
        "userPublicKey":        user_public_key,
        "wrapAndUnwrapSol":     True,
        "computeUnitPriceMicroLamports": 100_000,  # Priority fee: ~0.0001 SOL for high-speed listing block inclusion
        "asLegacyTransaction":  False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                JUPITER_SWAP_URL,
                json=payload,
                headers=_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"[DEXSwapper] Jupiter swap build {resp.status}: {text[:300]}")
                    return None
                data = await resp.json()
                return data.get("swapTransaction")
    except Exception as e:
        logger.error(f"[DEXSwapper] Jupiter swap build error: {e}")
        return None


async def _sign_and_send_transaction(
    tx_b64: str,
    private_key_b58: str,
    rpc_url: str = DEFAULT_SOLANA_RPC,
) -> Optional[str]:
    """
    Sign a Jupiter versioned transaction and broadcast it to Solana RPC.

    Returns:
        Transaction signature (base58) on success, None on failure.
    """
    try:
        from solders.transaction import VersionedTransaction
        from solders.signature import Signature

        # Decode the transaction
        raw_bytes = base64.b64decode(tx_b64)
        tx = VersionedTransaction.from_bytes(raw_bytes)

        # Sign with user's keypair
        kp = keypair_from_private_key(private_key_b58)
        # Re-sign the message
        msg_bytes = bytes(tx.message)
        sig = kp.sign_message(msg_bytes)

        # Inject signature
        signed_tx = VersionedTransaction.populate(tx.message, [sig])
        signed_bytes = bytes(signed_tx)
        tx_b64_signed = base64.b64encode(signed_bytes).decode("utf-8")

        # Send via RPC (skipPreflight=True for sub-second execution during listing spikes)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                tx_b64_signed,
                {
                    "encoding": "base64",
                    "skipPreflight": True,
                    "preflightCommitment": "processed",
                    "maxRetries": 5,
                }
            ]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rpc_url,
                json=payload,
                headers=_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                result = await resp.json()
                if "error" in result:
                    logger.error(f"[DEXSwapper] RPC sendTransaction error: {result['error']}")
                    return None
                sig_str = result.get("result")
                logger.info(f"[DEXSwapper] ✅ Transaction sent! Signature: {sig_str}")
                return sig_str

    except Exception as e:
        logger.error(f"[DEXSwapper] Sign & send error: {e}", exc_info=True)
        return None


async def execute_jupiter_swap(
    user: Dict[str, Any],
    contract_address: str,
    sol_amount: Optional[float] = None,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
) -> Dict[str, Any]:
    """
    High-level DEX swap: SOL → {contract_address} for a given user.

    Args:
        user:             User row dict (must have encrypted_solana_private_key, solana_wallet_address)
        contract_address: Token mint address (Solana Base58)
        sol_amount:       SOL to spend; falls back to user.solana_buy_amount_sol (default 0.1)
        slippage_bps:     Slippage tolerance

    Returns:
        {
          "success": True/False,
          "signature": "...",       # tx sig on success
          "in_sol": 0.1,
          "out_tokens": 1234.56,
          "price_impact_pct": 0.5,
          "latency_ms": 850,
          "error": "..."            # only on failure
        }
    """
    start_time = time.time()
    wallet_address = user.get("solana_wallet_address", "")
    encrypted_pk    = user.get("encrypted_solana_private_key", "")

    if not wallet_address or not encrypted_pk:
        return {"success": False, "error": "No Solana wallet configured for this user"}

    # Determine spend amount
    if sol_amount is None:
        sol_amount = float(user.get("solana_buy_amount_sol", 0.1))

    rpc_url = getattr(config, "SOLANA_RPC_URL", DEFAULT_SOLANA_RPC)

    # ── 1. Liquidity pre-check (non-blocking — log warning but proceed)
    liquidity = await _check_dexscreener_liquidity(contract_address)
    if liquidity < MIN_LIQUIDITY_USD:
        logger.warning(
            f"[DEXSwapper] Low liquidity warning: ${liquidity:,.0f} for {contract_address[:12]}… "
            f"(threshold ${MIN_LIQUIDITY_USD:,}). Proceeding anyway."
        )

    # ── 2. Get Jupiter quote
    quote = await get_jupiter_quote(contract_address, sol_amount, slippage_bps)
    if not quote:
        return {
            "success": False,
            "error": f"No Jupiter route found for contract {contract_address[:12]}… "
                     f"Token may not be listed on any DEX yet."
        }

    out_amount_raw = int(quote.get("outAmount", 0))
    price_impact   = float(quote.get("priceImpactPct", 0))
    logger.info(f"[DEXSwapper] Quote price impact: {price_impact:.2f}% (executing sniper swap)")

    # ── 3. Build swap transaction
    tx_b64 = await _build_swap_transaction(quote, wallet_address)
    if not tx_b64:
        return {"success": False, "error": "Failed to build swap transaction from Jupiter"}

    # ── 5. Sign & send (decrypt private key only during signing)
    private_key_b58 = decrypt_secret(encrypted_pk)
    sig = await _sign_and_send_transaction(tx_b64, private_key_b58, rpc_url)
    private_key_b58 = ""  # Clear from memory immediately

    if not sig:
        return {"success": False, "error": "Transaction failed to send to Solana network"}

    latency_ms = int((time.time() - start_time) * 1000)
    # Rough token amount (we don't know decimals here — DexScreener gives it)
    out_ui = out_amount_raw / 1_000_000  # Assume 6 decimals (most SPL tokens)

    return {
        "success":          True,
        "signature":        sig,
        "solscan_url":      f"https://solscan.io/tx/{sig}",
        "in_sol":           sol_amount,
        "out_amount_raw":   out_amount_raw,
        "out_tokens_approx": out_ui,
        "price_impact_pct": price_impact,
        "liquidity_usd":    liquidity,
        "latency_ms":       latency_ms,
    }


async def get_spl_raw_balance(wallet_address: str, token_mint: str, rpc_url: str = DEFAULT_SOLANA_RPC):
    """Get (raw_amount_int, decimals) for an SPL token owned by wallet."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"mint": token_mint},
            {"encoding": "jsonParsed", "commitment": "confirmed"}
        ]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5),
                headers={"Content-Type": "application/json"}
            ) as resp:
                data = await resp.json()
                accounts = (data.get("result") or {}).get("value", [])
                if not accounts:
                    return 0, 6
                acc_info = accounts[0].get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {})
                raw_amt = int(acc_info.get("amount", "0"))
                decimals = int(acc_info.get("decimals", 6))
                return raw_amt, decimals
    except Exception as e:
        logger.error(f"[DEXSwapper] Failed to get raw token balance: {e}")
        return 0, 6


async def execute_jupiter_sell(
    user: Dict[str, Any],
    token_mint: str,
    percentage: float = 1.0,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
) -> Dict[str, Any]:
    """
    Swap token back to SOL (Exit position / Take Profit).
    """
    start_time = time.time()
    wallet_address = user.get("solana_wallet_address", "")
    encrypted_pk   = user.get("encrypted_solana_private_key", "")
    rpc_url = getattr(config, "SOLANA_RPC_URL", DEFAULT_SOLANA_RPC)

    if not wallet_address or not encrypted_pk:
        return {"success": False, "error": "User Solana wallet not configured"}

    # 1. Fetch exact raw token balance
    raw_balance, decimals = await get_spl_raw_balance(wallet_address, token_mint, rpc_url)
    if raw_balance <= 0:
        return {"success": False, "error": "Zero token balance to sell"}

    sell_raw_amount = int(raw_balance * percentage)
    if sell_raw_amount <= 0:
        return {"success": False, "error": "Sell amount too small"}

    # 2. Get quote to swap Token -> SOL
    params = {
        "inputMint":   token_mint,
        "outputMint":  SOL_MINT,
        "amount":      sell_raw_amount,
        "slippageBps": slippage_bps,
        "onlyDirectRoutes": "false",
        "asLegacyTransaction": "false",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                JUPITER_QUOTE_URL,
                params=params,
                headers=_HEADERS,
                timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return {"success": False, "error": f"Jupiter sell quote failed: {text[:150]}"}
                quote = await resp.json()
    except Exception as e:
        return {"success": False, "error": f"Quote error: {str(e)}"}

    sol_out_lamports = int(quote.get("outAmount", 0))
    sol_out = sol_out_lamports / LAMPORTS_PER_SOL

    # 3. Build swap transaction
    tx_b64 = await _build_swap_transaction(quote, wallet_address)
    if not tx_b64:
        return {"success": False, "error": "Failed to build sell transaction"}

    # 4. Sign and send
    private_key_b58 = decrypt_secret(encrypted_pk)
    sig = await _sign_and_send_transaction(tx_b64, private_key_b58, rpc_url)
    private_key_b58 = ""

    if not sig:
        return {"success": False, "error": "Solana network transaction failed"}

    latency_ms = int((time.time() - start_time) * 1000)
    return {
        "success": True,
        "signature": sig,
        "solscan_url": f"https://solscan.io/tx/{sig}",
        "tokens_sold": sell_raw_amount / (10 ** decimals),
        "sol_received": sol_out,
        "latency_ms": latency_ms
    }
