"""Employer portal credentials — Iter 58.

Companies (employers) can store their login credentials for the government
labour portals (EPFO, ESIC, SSO Shram Suvidha) so the system can either
(a) auto-submit ECR / ESIC challans on their behalf later, or
(b) pre-fill the login form when opening the portal via browser automation.

Passwords are encrypted at rest using Fernet with a symmetric key derived
from the ``PORTAL_CRED_KEY`` environment variable. If the env var is
absent, we fall back to a locally-generated key stored on disk so the
system still works in dev — but production deployments MUST set the env
variable so credentials survive redeploys.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


_KEY_ENV = "PORTAL_CRED_KEY"
# Persist the fallback key under /app so it survives pod restarts in dev.
# Production deployments should set PORTAL_CRED_KEY env var so we never
# rely on the on-disk file at all.
_KEY_FILE = Path("/app/.sksharma_portal_cred.key")


def _load_key() -> bytes:
    """Return the Fernet key, preferring the env var. Falls back to a
    persisted file so restarts don't invalidate stored ciphertexts."""
    env_val = os.environ.get(_KEY_ENV, "").strip()
    if env_val:
        # Accept both raw base64 Fernet keys AND arbitrary secret strings
        # (which we hash into a 32-byte key for convenience).
        try:
            # Try direct — Fernet keys are 44-byte urlsafe base64.
            Fernet(env_val.encode())
            return env_val.encode()
        except Exception:
            digest = hashlib.sha256(env_val.encode("utf-8")).digest()
            return base64.urlsafe_b64encode(digest)
    if _KEY_FILE.exists():
        try:
            return _KEY_FILE.read_bytes().strip()
        except Exception:
            pass
    # Generate + persist a new key
    k = Fernet.generate_key()
    try:
        _KEY_FILE.write_bytes(k)
    except Exception:
        pass
    return k


_FERNET: Optional[Fernet] = None


def _fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_key())
    return _FERNET


def encrypt_password(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_password(ciphertext: str) -> Optional[str]:
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


PORTAL_KEYS = ["epfo", "esic", "shram_suvidha"]

PORTAL_LABELS = {
    "epfo": "EPFO — Employer Portal",
    "esic": "ESIC — Employer Portal",
    "shram_suvidha": "SSO Shram Suvidha Portal",
}


def sanitise_stored(portal_creds: dict) -> dict:
    """Prepare stored portal_credentials for display — mask the password."""
    out = {}
    if not portal_creds:
        return {}
    for k in PORTAL_KEYS:
        v = (portal_creds or {}).get(k) or {}
        out[k] = {
            "label": PORTAL_LABELS[k],
            "username": v.get("username") or "",
            "notes": v.get("notes") or "",
            # Never leak the ciphertext OR plaintext — only reveal presence.
            "has_password": bool(v.get("password_cipher")),
            "updated_at": v.get("updated_at"),
        }
    return out
