"""
Solana Per-User Wallet Manager
==============================
Generates, encrypts, stores and retrieves Solana wallets for each bot user.
Uses `solders` (Rust-based, fast) for Ed25519 keypair generation and signing.
Private keys are encrypted using Fernet / ENCRYPTION_MASTER_KEY.
"""

import logging
import base64
import base58
from typing import Tuple, Optional, List, Dict, Any
import aiohttp

logger = logging.getLogger(__name__)

# ─── Solana constants ─────────────────────────────────────────────────────────
SOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_SOLANA_RPC = "https://api.mainnet-beta.solana.com"

try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer as sol_transfer
    from solders.transaction import Transaction
    from solders.message import Message
    from solders.hash import Hash
    _SOLDERS_AVAILABLE = True
except ImportError:
    _SOLDERS_AVAILABLE = False
    logger.warning("[SolanaWallet] solders not available — wallet features disabled")


def generate_solana_keypair() -> Tuple[str, str]:
    """Generate fresh keypair -> (pubkey, privkey_b58)."""
    if not _SOLDERS_AVAILABLE:
        raise RuntimeError("solders package is not installed")
    kp = Keypair()
    pubkey = str(kp.pubkey())
    secret_bytes = bytes(kp)
    private_key_b58 = base58.b58encode(secret_bytes).decode("utf-8")
    return pubkey, private_key_b58


def keypair_from_private_key(private_key_b58: str):
    """Reconstruct a solders Keypair from stored Base58 private key."""
    if not _SOLDERS_AVAILABLE:
        raise RuntimeError("solders not available")
    secret_bytes = base58.b58decode(private_key_b58)
    return Keypair.from_bytes(secret_bytes)


def get_public_key_from_private(private_key_b58: str) -> str:
    """Derive public key (wallet address) from private key."""
    kp = keypair_from_private_key(private_key_b58)
    return str(kp.pubkey())


async def get_solana_balance(wallet_address: str, rpc_url: str = DEFAULT_SOLANA_RPC) -> float:
    """Query SOL balance for a wallet address."""
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
        logger.error(f"[SolanaWallet] getBalance failed: {e}")
        return 0.0


async def get_user_spl_tokens(wallet_address: str, rpc_url: str = DEFAULT_SOLANA_RPC) -> List[Dict[str, Any]]:
    """
    Retrieve all SPL token accounts owned by this wallet with positive balances.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"programId": TOKEN_PROGRAM_ID},
            {"encoding": "jsonParsed", "commitment": "confirmed"}
        ]
    }
    tokens = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=6),
                headers={"Content-Type": "application/json"}
            ) as resp:
                data = await resp.json()
                accounts = (data.get("result") or {}).get("value", [])
                for acc in accounts:
                    info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                    token_amount = info.get("tokenAmount", {})
                    ui_amount = float(token_amount.get("uiAmount") or 0.0)
                    if ui_amount > 0:
                        mint = info.get("mint", "")
                        tokens.append({
                            "mint": mint,
                            "symbol": mint[:4] + "…" + mint[-4:],  # Fallback symbol
                            "amount": ui_amount,
                            "decimals": token_amount.get("decimals", 6)
                        })
    except Exception as e:
        logger.error(f"[SolanaWallet] get_user_spl_tokens failed: {e}")
    return tokens


async def send_sol(
    sender_priv_b58: str,
    to_address: str,
    sol_amount: float,
    rpc_url: str = DEFAULT_SOLANA_RPC
) -> Dict[str, Any]:
    """
    Send SOL from user's wallet to an external recipient address.
    """
    if not _SOLDERS_AVAILABLE:
        return {"success": False, "error": "solders library not available"}

    try:
        sender_kp = keypair_from_private_key(sender_priv_b58)
        sender_pub = sender_kp.pubkey()
        recipient_pub = Pubkey.from_string(to_address)
        lamports = int(sol_amount * LAMPORTS_PER_SOL)

        if lamports <= 0:
            return {"success": False, "error": "Invalid SOL amount"}

        # 1. Fetch recent blockhash
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": [{"commitment": "confirmed"}]
                },
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                res = await r.json()
                bh_str = res.get("result", {}).get("value", {}).get("blockhash")
                if not bh_str:
                    return {"success": False, "error": "Failed to get recent blockhash from Solana RPC"}
                blockhash = Hash.from_string(bh_str)

            # 2. Build transfer instruction & sign transaction
            ix = sol_transfer(TransferParams(
                from_pubkey=sender_pub,
                to_pubkey=recipient_pub,
                lamports=lamports
            ))
            msg = Message([ix], sender_pub)
            tx = Transaction([sender_kp], msg, blockhash)
            tx_b64 = base64.b64encode(bytes(tx)).decode("utf-8")

            # 3. Broadcast to Solana RPC
            async with session.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        tx_b64,
                        {
                            "encoding": "base64",
                            "skipPreflight": False,
                            "preflightCommitment": "confirmed"
                        }
                    ]
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                send_res = await r.json()
                if "error" in send_res:
                    err_msg = send_res["error"].get("message", str(send_res["error"]))
                    return {"success": False, "error": err_msg}
                sig = send_res.get("result")
                return {
                    "success": True,
                    "signature": sig,
                    "solscan_url": f"https://solscan.io/tx/{sig}",
                    "amount_sol": sol_amount,
                    "recipient": to_address
                }
    except Exception as e:
        logger.error(f"[SolanaWallet] send_sol failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
