"""
TON Blockchain wallet service.
Creates wallets using tonsdk for new users.
Private keys are AES-256 encrypted before storage.
"""

import logging
from tonsdk.contract.wallet import Wallets, WalletVersionEnum
from tonsdk.utils import bytes_to_b64str, b64str_to_bytes

from utils.encryption import encrypt_private_key, decrypt_private_key

logger = logging.getLogger("sidiapp.ton")


def create_wallet() -> tuple[str, str]:
    """
    Create a new TON wallet.
    Returns (wallet_address, encrypted_private_key).
    """
    try:
        mnemonics, pub_k, priv_k, wallet = Wallets.create(
            version=WalletVersionEnum.v4r2,
            workchain=0,
        )

        # Get the wallet address as a friendly string
        address = wallet.address.to_string(True, True, False)

        # Serialize the private key (mnemonics) for storage
        mnemonic_string = " ".join(mnemonics)
        encrypted_key = encrypt_private_key(mnemonic_string)

        logger.info(f"New TON wallet created: {address[:20]}...")
        return address, encrypted_key

    except Exception as e:
        logger.error(f"TON wallet creation error: {e}")
        raise


def get_wallet_from_key(encrypted_key: str) -> tuple[str, list[str]]:
    """
    Recover wallet from encrypted private key.
    Returns (wallet_address, mnemonics_list).
    """
    try:
        mnemonic_string = decrypt_private_key(encrypted_key)
        mnemonics = mnemonic_string.split(" ")

        _mnemonics, _pub_k, _priv_k, wallet = Wallets.from_mnemonics(
            mnemonics=mnemonics,
            version=WalletVersionEnum.v4r2,
            workchain=0,
        )

        address = wallet.address.to_string(True, True, False)
        return address, mnemonics

    except Exception as e:
        logger.error(f"TON wallet recovery error: {e}")
        raise


def get_wallet_address(encrypted_key: str) -> str:
    """Get wallet address from encrypted key without exposing mnemonics."""
    address, _ = get_wallet_from_key(encrypted_key)
    return address


def format_wallet_address(address: str) -> str:
    """Format wallet address for display (truncated)."""
    if len(address) > 16:
        return f"{address[:8]}...{address[-8:]}"
    return address
