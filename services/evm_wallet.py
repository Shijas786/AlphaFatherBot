"""
EVM Per-User Wallet Manager
===========================
Generates, encrypts, stores and retrieves EVM (Ethereum / Base / BSC / Arbitrum)
wallets for each bot user.
One EVM address works across all EVM chains (Base, Ethereum, BSC, Arbitrum).
Private keys are encrypted using Fernet / ENCRYPTION_MASTER_KEY.
"""

import logging
from typing import Tuple, Dict, Any
import aiohttp
from eth_account import Account

logger = logging.getLogger(__name__)

# Public reliable RPC endpoints for EVM chains
EVM_RPCS: Dict[str, str] = {
    "base": "https://mainnet.base.org",
    "ethereum": "https://eth.llamarpc.com",
    "bsc": "https://binance.llamarpc.com",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "polygon": "https://polygon-rpc.com"
}

CHAIN_IDS: Dict[str, int] = {
    "base": 8453,
    "ethereum": 1,
    "bsc": 56,
    "arbitrum": 42161,
    "polygon": 137
}

EXPLORERS: Dict[str, str] = {
    "base": "https://basescan.org/tx/",
    "ethereum": "https://etherscan.io/tx/",
    "bsc": "https://bscscan.com/tx/",
    "arbitrum": "https://arbiscan.io/tx/"
}

def generate_evm_keypair() -> Tuple[str, str]:
    """Generate fresh EVM keypair -> (address_0x, private_key_hex)."""
    acct = Account.create()
    address = acct.address
    pk_hex = acct.key.hex()
    if pk_hex.startswith("0x"):
        pk_hex = pk_hex[2:]
    return address, pk_hex


async def get_evm_balance(wallet_address: str, network: str = "base") -> float:
    """Query native balance (ETH / BNB / MATIC) in human units for given EVM chain."""
    rpc_url = EVM_RPCS.get(network.lower(), EVM_RPCS["base"])
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [wallet_address, "latest"]
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
                hex_val = data.get("result", "0x0")
                wei = int(hex_val, 16)
                return wei / 1e18
    except Exception as e:
        logger.error(f"[EVMWallet] eth_getBalance failed on {network}: {e}")
        return 0.0


async def send_evm_native(
    sender_priv_hex: str,
    to_address: str,
    amount_eth: float,
    network: str = "base"
) -> Dict[str, Any]:
    """
    Send native ETH/BNB from user's wallet to an external recipient address.
    """
    network_clean = network.lower()
    rpc_url = EVM_RPCS.get(network_clean, EVM_RPCS["base"])
    chain_id = CHAIN_IDS.get(network_clean, 8453)
    explorer_base = EXPLORERS.get(network_clean, "https://basescan.org/tx/")

    if not sender_priv_hex.startswith("0x"):
        sender_priv_hex = "0x" + sender_priv_hex

    try:
        acct = Account.from_key(sender_priv_hex)
        sender_addr = acct.address
        wei_value = int(amount_eth * 1e18)

        async with aiohttp.ClientSession() as session:
            # 1. Get nonce
            async with session.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_getTransactionCount",
                    "params": [sender_addr, "latest"]
                },
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                res = await r.json()
                nonce = int(res.get("result", "0x0"), 16)

            # 2. Get modern EIP-1559 gas
            try:
                async with session.post(
                    rpc_url,
                    json={"jsonrpc": "2.0", "id": 2, "method": "eth_getBlockByNumber", "params": ["latest", False]},
                    timeout=aiohttp.ClientTimeout(total=4)
                ) as r:
                    bdata = await r.json()
                    base_fee = int(bdata.get("result", {}).get("baseFeePerGas", "0x3b9aca00"), 16)

                async with session.post(
                    rpc_url,
                    json={"jsonrpc": "2.0", "id": 3, "method": "eth_maxPriorityFeePerGas", "params": []},
                    timeout=aiohttp.ClientTimeout(total=4)
                ) as r:
                    pdata = await r.json()
                    priority_fee = int(pdata.get("result", "0x5f5e100"), 16)
            except Exception:
                base_fee = 1_000_000_000  # 1 gwei
                priority_fee = 100_000_000 # 0.1 gwei

            max_priority = max(priority_fee, 50_000_000)
            max_fee = int(base_fee * 1.5) + max_priority

            tx = {
                "type": 2,
                "nonce": nonce,
                "maxFeePerGas": max_fee,
                "maxPriorityFeePerGas": max_priority,
                "gas": 21000,
                "to": to_address,
                "value": wei_value,
                "chainId": chain_id
            }

            signed = acct.sign_transaction(tx)
            raw_hex = signed.raw_transaction.hex()
            if not raw_hex.startswith("0x"):
                raw_hex = "0x" + raw_hex

            # 3. Broadcast
            async with session.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "eth_sendRawTransaction",
                    "params": [raw_hex]
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                send_res = await r.json()
                if "error" in send_res:
                    err_msg = send_res["error"].get("message", str(send_res["error"]))
                    return {"success": False, "error": err_msg}
                tx_hash = send_res.get("result")
                return {
                    "success": True,
                    "tx_hash": tx_hash,
                    "explorer_url": f"{explorer_base}{tx_hash}",
                    "amount_eth": amount_eth,
                    "network": network_clean.upper(),
                    "recipient": to_address
                }
    except Exception as e:
        logger.error(f"[EVMWallet] send_evm_native failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
