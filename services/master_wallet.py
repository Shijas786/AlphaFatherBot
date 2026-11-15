"""
Master HD Wallet Manager (BIP-39 / BIP-44)
===========================================
Derives child Solana and EVM wallets deterministically from a single
Master 12-Word Seed Phrase.

Derivation Paths:
  - Solana: m/44'/501'/{account_index}'/0' (Standard Phantom / Solflare path)
  - EVM:    m/44'/60'/0'/0/{account_index}  (Standard MetaMask / BIP-44 path)
"""

import logging
from typing import Tuple, Optional
import base58
from bip_utils import (
    Bip39SeedGenerator,
    Bip44,
    Bip44Coins,
    Bip44Changes
)
from solders.keypair import Keypair
import config

logger = logging.getLogger(__name__)

_SEED_BYTES: Optional[bytes] = None

def _get_seed_bytes() -> bytes:
    """Cache the master seed bytes derived from MASTER_WALLET_MNEMONIC."""
    global _SEED_BYTES
    if _SEED_BYTES is None:
        mnemonic = (config.MASTER_WALLET_MNEMONIC or "").strip()
        if not mnemonic:
            raise ValueError(
                "MASTER_WALLET_MNEMONIC is not configured in .env! "
                "Please add your 12-word master seed phrase."
            )
        _SEED_BYTES = Bip39SeedGenerator(mnemonic).Generate()
    return _SEED_BYTES

def derive_solana_wallet(account_index: int) -> Tuple[str, str]:
    """
    Derive child Solana wallet for a user by index.
    Standard path: m/44'/501'/{account_index}'/0'

    Returns:
        (solana_address, private_key_base58)
    """
    seed_bytes = _get_seed_bytes()
    sol_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
    child = sol_ctx.Purpose().Coin().Account(account_index).Change(Bip44Changes.CHAIN_EXT)
    
    priv_seed = child.PrivateKey().Raw().ToBytes()
    kp = Keypair.from_seed(priv_seed)
    
    pubkey = str(kp.pubkey())
    priv_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    return pubkey, priv_b58

def derive_evm_wallet(account_index: int) -> Tuple[str, str]:
    """
    Derive child EVM (Base / Ethereum / BSC / Arbitrum) wallet by index.
    Standard path: m/44'/60'/0'/0/{account_index}

    Returns:
        (address_0x, private_key_hex)
    """
    seed_bytes = _get_seed_bytes()
    eth_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
    child = eth_ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(account_index)
    
    address = child.PublicKey().ToAddress()
    priv_hex = child.PrivateKey().Raw().ToHex()
    return address, priv_hex
