"""SEC-003 — Encryption-at-rest for portal credentials (EPFO / ESIC / etc.).

Fernet symmetric encryption. Key resolution order:
  1. ``PORTAL_CREDS_KEY`` in backend/.env (recommended — the VPS deploy
     script generates one automatically if missing).
  2. Fallback: a stable key derived from MONGO_URL + DB_NAME so encryption
     works out-of-the-box per environment.

Stored ciphertexts carry the ``enc::`` prefix so plaintext legacy values
remain readable during migration; ``decrypt_secret`` transparently returns
plaintext values as-is.
"""
import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

ENC_PREFIX = "enc::"
MASK = "••••••"  # what the API returns instead of the real password


def _fernets() -> list:
    """Candidate keys, primary first. Encryption always uses the primary
    (env) key; decryption tries all candidates so values written before
    ``PORTAL_CREDS_KEY`` was configured (fallback key) stay readable."""
    materials = []
    explicit = (os.environ.get("PORTAL_CREDS_KEY") or "").strip()
    if explicit:
        materials.append(explicit)
    materials.append(
        "sks-portal-vault::"
        f"{os.environ.get('MONGO_URL', '')}/{os.environ.get('DB_NAME', '')}"
    )
    out = []
    for m in materials:
        digest = hashlib.sha256(m.encode("utf-8")).digest()
        out.append(Fernet(base64.urlsafe_b64encode(digest)))
    return out


def _fernet() -> Fernet:
    return _fernets()[0]


def is_encrypted(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    """Encrypt a plaintext secret. Already-encrypted / empty values pass through."""
    if not value or not isinstance(value, str) or is_encrypted(value):
        return value or None
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return ENC_PREFIX + token


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Decrypt an ``enc::`` value; legacy plaintext passes through unchanged."""
    if not value or not isinstance(value, str):
        return value or None
    if not is_encrypted(value):
        return value
    token = value[len(ENC_PREFIX):].encode("ascii")
    for f in _fernets():
        try:
            return f.decrypt(token).decode("utf-8")
        except (InvalidToken, ValueError):
            continue
    # Unknown/rotated key — treat as unreadable rather than crashing RPA.
    return None
