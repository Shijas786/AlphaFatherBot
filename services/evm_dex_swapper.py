"""
EVM DEX Swapper
===============
Modern multi-chain decentralized exchange swapper for EVM chains:
  - Base (L2 - Chain ID 8453)
  - Ethereum Mainnet (L1 - Chain ID 1)
  - Arbitrum One (L2 - Chain ID 42161)
  - BSC / BNB Chain (Chain ID 56)

Uses KyberSwap Aggregator (Uniswap v2/v3, Aerodrome, Curve) with dynamic
EIP-1559 gas calculation (baseFee + priorityFee) for sub-second trade execution.
"""

import logging
import time
import aiohttp
from typing import Dict, Any, Optional
from eth_account import Account
from database.encryption import decrypt_secret
from services.evm_wallet import EVM_RPCS, CHAIN_IDS, EXPLORERS

logger = logging.getLogger(__name__)

# Native currency placeholder for aggregator swaps
NATIVE_TOKEN = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

# KyberSwap Aggregator Base URL
KYBERSWAP_BASE_URL = "https://aggregator-api.kyberswap.com"

# Network aliases
NETWORK_MAP = {
    "base": "base",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "mainnet": "ethereum",
    "arbitrum": "arbitrum",
    "arb": "arbitrum",
    "bsc": "bsc",
    "binance": "bsc",
    "polygon": "polygon"
}


async def get_eip1559_gas_params(session: aiohttp.ClientSession, rpc_url: str) -> Dict[str, int]:
    """
    Fetch modern EIP-1559 gas fees (baseFeePerGas + maxPriorityFeePerGas).
    Post-Dencun gas on L1 runs at 1-3 gwei; on Base/Arbitrum it runs at ~0.001 gwei.
    """
    try:
        # 1. Fetch latest block for baseFeePerGas
        async with session.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber", "params": ["latest", False]},
            timeout=aiohttp.ClientTimeout(total=4)
        ) as r:
            block_data = await r.json()
            base_fee_hex = block_data.get("result", {}).get("baseFeePerGas", "0x3b9aca00")
            base_fee = int(base_fee_hex, 16)

        # 2. Fetch priority fee recommendation
        async with session.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 2, "method": "eth_maxPriorityFeePerGas", "params": []},
            timeout=aiohttp.ClientTimeout(total=4)
        ) as r:
            prio_data = await r.json()
            prio_fee_hex = prio_data.get("result", "0x5f5e100") # 0.1 gwei fallback
            priority_fee = int(prio_fee_hex, 16)

        # Fast inclusion: priority fee + 2x base fee buffer
        max_priority = max(priority_fee, 50_000_000) # min 0.05 gwei
        max_fee = int(base_fee * 1.5) + max_priority

        return {
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": max_priority
        }
    except Exception as e:
        logger.warning(f"[EVMDex] EIP-1559 gas query failed: {e}. Using fallback gas.")
        return {
            "maxFeePerGas": 3_000_000_000, # 3 gwei
            "maxPriorityFeePerGas": 100_000_000 # 0.1 gwei
        }


async def execute_evm_swap(
    user: Dict[str, Any],
    network: str,
    contract_address: str,
    eth_amount: float,
    slippage_bps: int = 150 # 1.5% slippage
) -> Dict[str, Any]:
    """
    Execute instant market swap on EVM (Base L2, Ethereum L1, Arbitrum, BSC).
    Swaps native ETH/BNB for target token contract via KyberSwap / Uniswap.
    """
    canon_network = NETWORK_MAP.get(network.lower(), "base")
    rpc_url = EVM_RPCS.get(canon_network, EVM_RPCS["base"])
    chain_id = CHAIN_IDS.get(canon_network, 8453)

    enc_pk = user.get("encrypted_evm_private_key", "")
    if not enc_pk:
        return {"success": False, "error": "No EVM private key found for user."}

    try:
        pk_hex = decrypt_secret(enc_pk)
        acct = Account.from_key(pk_hex)
        sender_address = acct.address
    except Exception as e:
        return {"success": False, "error": f"Failed to decrypt EVM wallet: {e}"}

    wei_amount = int(eth_amount * 1e18)
    if wei_amount <= 0:
        return {"success": False, "error": "Invalid ETH buy amount."}

    logger.info(
        f"[EVMDex] Initiating swap on {canon_network.upper()} | Token: {contract_address} | "
        f"Amount: {eth_amount} ETH | Sender: {sender_address}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
        "Accept": "application/json"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        # Step 1: Query Aggregator Route
        route_url = (
            f"{KYBERSWAP_BASE_URL}/{canon_network}/api/v1/routes"
            f"?tokenIn={NATIVE_TOKEN}&tokenOut={contract_address}&amountIn={wei_amount}"
        )

        try:
            async with session.get(route_url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    return {"success": False, "error": f"DEX route lookup failed ({resp.status}): {err_txt[:100]}"}

                route_res = await resp.json()
                route_summary = route_res.get("data", {}).get("routeSummary")
                if not route_summary:
                    return {"success": False, "error": f"No liquid DEX pool found for {contract_address} on {canon_network}"}

                tokens_approx = float(route_summary.get("amountOut", 0))
                price_impact = float(route_summary.get("extraFee", {}).get("feeAmount", 0))

        except Exception as e:
            return {"success": False, "error": f"Route request error: {e}"}

        # Step 2: Build Executable Swap Transaction
        build_url = f"{KYBERSWAP_BASE_URL}/{canon_network}/api/v1/route/build"
        build_payload = {
            "routeSummary": route_summary,
            "sender": sender_address,
            "recipient": sender_address,
            "slippageTolerance": slippage_bps
        }

        try:
            async with session.post(build_url, json=build_payload, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    return {"success": False, "error": f"Build swap calldata failed: {err_txt[:100]}"}

                build_res = await resp.json()
                tx_data = build_res.get("data", {})
                router_address = tx_data.get("routerAddress")
                calldata_hex = tx_data.get("data")
                gas_limit = int(tx_data.get("gas", 350000))
                value_to_send = int(tx_data.get("value", wei_amount))

        except Exception as e:
            return {"success": False, "error": f"Transaction build error: {e}"}

        # Step 3: Fetch Nonce and EIP-1559 Gas
        try:
            async with session.post(
                rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionCount", "params": [sender_address, "latest"]},
                timeout=aiohttp.ClientTimeout(total=4)
            ) as r:
                nonce_data = await r.json()
                nonce = int(nonce_data.get("result", "0x0"), 16)

            gas_params = await get_eip1559_gas_params(session, rpc_url)

        except Exception as e:
            return {"success": False, "error": f"Failed to fetch nonce/gas from {canon_network}: {e}"}

        # Step 4: Sign EIP-1559 Transaction
        tx = {
            "type": 2,
            "chainId": chain_id,
            "nonce": nonce,
            "to": router_address,
            "value": value_to_send,
            "data": calldata_hex,
            "gas": int(gas_limit * 1.25), # 25% safety buffer for AMM execution
            "maxFeePerGas": gas_params["maxFeePerGas"],
            "maxPriorityFeePerGas": gas_params["maxPriorityFeePerGas"]
        }

        try:
            signed_tx = acct.sign_transaction(tx)
            raw_tx_hex = signed_tx.raw_transaction.hex()
            if not raw_tx_hex.startswith("0x"):
                raw_tx_hex = "0x" + raw_tx_hex
        except Exception as e:
            return {"success": False, "error": f"Failed to sign EVM transaction: {e}"}

        # Step 5: Broadcast to RPC
        try:
            async with session.post(
                rpc_url,
                json={"jsonrpc": "2.0", "id": 3, "method": "eth_sendRawTransaction", "params": [raw_tx_hex]},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                broadcast_data = await r.json()
                if "error" in broadcast_data:
                    err_msg = broadcast_data["error"].get("message", str(broadcast_data["error"]))
                    return {"success": False, "error": f"RPC rejected tx: {err_msg}"}

                tx_hash = broadcast_data.get("result", "")
                if not tx_hash:
                    return {"success": False, "error": f"Empty tx hash returned: {broadcast_data}"}

                logger.info(f"[EVMDex] Swap transaction broadcast successfully! Tx: {tx_hash} on {canon_network.upper()}")

                explorer_prefix = EXPLORERS.get(canon_network, "https://basescan.org/tx/")
                return {
                    "success": True,
                    "signature": tx_hash,
                    "tx_hash": tx_hash,
                    "network": canon_network,
                    "out_tokens_approx": tokens_approx,
                    "eth_spent": eth_amount,
                    "price_impact_pct": price_impact,
                    "explorer_url": f"{explorer_prefix}{tx_hash}"
                }

        except Exception as e:
            return {"success": False, "error": f"Broadcast failed: {e}"}
