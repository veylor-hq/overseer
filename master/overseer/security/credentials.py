"""Cryptographic helpers for tokens, credentials, hashing and encryption."""

import base64
import hashlib
import hmac
import os
import secrets
from typing import Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from overseer.config import get_settings


def generate_id(prefix: str) -> str:
    """Generate a high-entropy prefixed identifier (e.g. ws_..., node_..., svc_...)."""
    return f"{prefix}_{secrets.token_hex(12)}"


def generate_activation_token() -> Tuple[str, str]:
    """
    Generate a one-time high-entropy activation token and its SHA-256 hash.
    Returns: (raw_token, token_hash)
    The raw token is presented once to the admin; only the hash is persisted in DB.
    """
    raw_token = f"voy_act_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_token(raw_token: str) -> str:
    """Compute SHA-256 hex digest of a token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_node_credential() -> Tuple[str, str]:
    """
    Generate a permanent node credential secret and its salted HMAC-SHA256 hash.
    Returns: (raw_secret, secret_hash)
    """
    raw_secret = f"voy_sec_{secrets.token_urlsafe(40)}"
    settings = get_settings()
    secret_hash = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw_secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return raw_secret, secret_hash


def verify_node_credential(raw_secret: str, stored_hash: str) -> bool:
    """Constant-time verification of node secret."""
    settings = get_settings()
    expected_hash = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw_secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_hash, stored_hash)


def encrypt_secret(plain_text: str) -> str:
    """Encrypt sensitive string (e.g. Telegram bot token) using AES-256-GCM."""
    if not plain_text:
        return ""
    settings = get_settings()
    key = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_secret(cipher_b64: str) -> str:
    """Decrypt AES-256-GCM encrypted string."""
    if not cipher_b64:
        return ""
    try:
        settings = get_settings()
        key = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        data = base64.b64decode(cipher_b64.encode("utf-8"))
        nonce = data[:12]
        ciphertext = data[12:]
        aesgcm = AESGCM(key)
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception:
        return ""
