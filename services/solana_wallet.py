"""
Solana Per-User Wallet Manager
==============================
Generates, encrypts, stores and retrieves Solana wallets for each bot user.
Uses `solders` (Rust-based, fast) for Ed25519 keypair generation.
Private keys are encrypted using the same Fernet/ENCRYPTION_MASTER_KEY
infrastructure as Binance API keys.
"""

import logging
import base64
import base58
import struct
from typing import Tuple, Optional
import aiohttp

logger = logging.getLogger(__name__)

# ─── Solana constants ─────────────────────────────────────────────────────────
SOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# ─── Import solders (installed as dependency) ─────────────────────────────────
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    _SOLDERS_AVAILABLE = True
except ImportError:
    _SOLDERS_AVAILABLE = False
    logger.warning("[SolanaWallet] solders not available — wallet generation disabled")


def generate_solana_keypair() -> Tuple[str, str]:
    """
    Generate a fresh Solana keypair.

    Returns:
        (public_key_str, private_key_base58)
        public_key_str:    Base58 wallet address (44 chars)
        private_key_base58: Base58-encoded 64-byte secret key (for storage)
    """
    if not _SOLDERS_AVAILABLE:
        raise RuntimeError("solders package is not installed. Run: pip install solders>=0.21.0")

    kp = Keypair()
    pubkey = str(kp.pubkey())

    # solders stores the secret key as a 64-byte array (seed + pubkey)
    secret_bytes = bytes(kp)          # 64 bytes: 32-byte seed || 32-byte pubkey
    private_key_b58 = base58.b58encode(secret_bytes).decode("utf-8")

    return pubkey, private_key_b58


def keypair_from_private_key(private_key_b58: str):
    """
    Reconstruct a solders Keypair from stored Base58 private key.
    Used during signing (swap execution).
    """
    if not _SOLDERS_AVAILABLE:
        raise RuntimeError("solders not available")
    secret_bytes = base58.b58decode(private_key_b58)
    return Keypair.from_bytes(secret_bytes)


def get_public_key_from_private(private_key_b58: str) -> str:
    """Derive the public key (wallet address) from an encrypted private key."""
    kp = keypair_from_private_key(private_key_b58)
    return str(kp.pubkey())


async def get_solana_balance(wallet_address: str, rpc_url: str = DEFAULT_SOLANA_RPC) -> float:
    """
    Query the SOL balance (in SOL, not lamports) for a wallet address.
    Uses the Solana JSON-RPC `getBalance` method.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [wallet_address, {"commitment": "confirmed"}]
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
                lamports = data.get("result", {}).get("value", 0)
                return lamports / LAMPORTS_PER_SOL
    except Exception as e:
        logger.error(f"[SolanaWallet] getBalance failed for {wallet_address[:8]}…: {e}")
        return 0.0


async def get_spl_token_balance(wallet_address: str, mint_address: str, rpc_url: str = DEFAULT_SOLANA_RPC) -> float:
    """
    Query the balance of a specific SPL token for a wallet.
    Returns the UI amount (human-readable, e.g. 1.5 SANC).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"mint": mint_address},
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
                    return 0.0
                amount = (
                    accounts[0]
                    .get("account", {})
                    .get("data", {})
                    .get("parsed", {})
                    .get("info", {})
                    .get("tokenAmount", {})
                    .get("uiAmount", 0.0)
                )
                return float(amount or 0.0)
    except Exception as e:
        logger.error(f"[SolanaWallet] getTokenAccountsByOwner failed: {e}")
        return 0.0
