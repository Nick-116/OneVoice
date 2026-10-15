"""Shared crypto helpers: password hashing, token hashing, secret encryption."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_ph = PasswordHasher()  # argon2id, library defaults (64 MiB, t=3)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# A pre-computed hash so unknown usernames take the same time as wrong passwords.
DUMMY_PASSWORD_HASH = _ph.hash("not-a-real-password-" + secrets.token_hex(8))


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _fernet() -> Fernet:
    # Derive a Fernet key from the app secret so operators manage a single secret.
    digest = hashlib.sha256(("fernet:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None


# ---- Audio sender tokens -------------------------------------------------
# Format: cs_<sender uuid hex>_<43 char secret>. The secret has 256 bits of
# entropy, so a fast SHA-256 hash is appropriate (no need for argon2).

def new_sender_token(sender_id_hex: str) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    token = f"cs_{sender_id_hex}_{secret}"
    return token, sha256_hex(secret)


def parse_sender_token(token: str) -> tuple[str, str] | None:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "cs" or len(parts[1]) != 32 or len(parts[2]) < 32:
        return None
    try:
        int(parts[1], 16)
    except ValueError:
        return None
    return parts[1], parts[2]


def ip_allowed(ip: str, cidrs: list[str]) -> bool:
    if not cidrs:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False
