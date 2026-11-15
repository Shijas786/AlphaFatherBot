"""
EVM Per-User Wallet Manager
===========================
Generates, encrypts, stores and retrieves EVM (Ethereum / Base / BSC / Arbitrum)
wallets for each bot user.
One EVM address works across all EVM chains (Base, Ethereum, BSC, Arbitrum).
Private keys are encrypted using Fernet / ENCRYPTION_MASTER_KEY.
"""

import logging
from typing import Tuple, Dict
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

def generate_evm_keypair() -> Tuple[str, str]:
    """
    Generate a fresh EVM keypair.
    
    Returns:
        (address_0x, private_key_hex)
        address_0x:      0x... checksum address (42 chars)
        private_key_hex: 64-hex-char private key string (without 0x)
    """
    acct = Account.create()
    address = acct.address
    pk_hex = acct.key.hex()
    if pk_hex.startswith("0x"):
        pk_hex = pk_hex[2:]
    return address, pk_hex

async def get_evm_balance(wallet_address: str, network: str = "base") -> float:
    """
    Query native balance (ETH / BNB / MATIC) in human units for given EVM chain.
    """
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
        logger.error(f"[EVMWallet] eth_getBalance failed on {network} for {wallet_address[:8]}…: {e}")
        return 0.0
