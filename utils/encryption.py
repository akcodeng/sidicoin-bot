"""
AES-256-CBC encryption for TON wallet private keys.
Keys are encrypted before storage in Redis and decrypted only when needed for signing.
"""

import os
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

if not ENCRYPTION_KEY:
    import logging
    logging.getLogger("sidiapp.encryption").warning(
        "ENCRYPTION_KEY not set! Private key encryption will be insecure."
    )


def _derive_key(passphrase: str) -> bytes:
    """Derive a 32-byte AES-256 key from the passphrase using SHA-256."""
    return hashlib.sha256(passphrase.encode("utf-8")).digest()


def encrypt_private_key(plain_text: str) -> str:
    """
    Encrypt a private key string with AES-256-CBC.
    Returns base64-encoded string: iv + ciphertext.
    """
    key = _derive_key(ENCRYPTION_KEY)
    iv = os.urandom(16)

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(plain_text.encode("utf-8")) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()

    # Concatenate IV + ciphertext and base64 encode
    encrypted = base64.b64encode(iv + ciphertext).decode("utf-8")
    return encrypted


def decrypt_private_key(encrypted_text: str) -> str:
    """
    Decrypt an AES-256-CBC encrypted private key.
    Expects base64-encoded string: iv (16 bytes) + ciphertext.
    """
    key = _derive_key(ENCRYPTION_KEY)
    raw = base64.b64decode(encrypted_text)

    iv = raw[:16]
    ciphertext = raw[16:]

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plain_text = unpadder.update(padded_data) + unpadder.finalize()

    return plain_text.decode("utf-8")
