"""Password hashing. Per-user random salt, PBKDF2-HMAC-SHA256, constant-time compare. Never log passwords."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_ITER = 200_000


def hash_password(password: str, iterations: int | None = None) -> str:
    iterations = iterations or _ITER
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, it, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(it))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False
