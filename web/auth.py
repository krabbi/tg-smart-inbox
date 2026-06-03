"""Authentication utilities for the tg-smart-inbox web UI companion.

Pure functions only — no FastAPI imports.  All three utilities are safe to
import and unit-test without a running application.
"""

import hashlib
import hmac
import time

import jwt


def verify_telegram_login(data: dict, bot_token: str) -> bool:
    """Verify a Telegram Login Widget payload against the bot token.

    Builds the check string from all fields except ``hash``, sorted
    alphabetically and joined with newlines, then computes
    HMAC-SHA256(SHA256(bot_token), check_string).  Returns True only when
    the computed hash matches ``data["hash"]`` AND ``auth_date`` is not older
    than 86 400 seconds (one day).  Returns False for any tampered or expired
    payload.
    """
    received_hash = data.get("hash", "")
    auth_date = data.get("auth_date")

    if not received_hash or auth_date is None:
        return False

    # Reject payloads older than one day.
    try:
        if time.time() - int(auth_date) > 86400:
            return False
    except (ValueError, TypeError):
        return False

    # Build the check string: key=value pairs sorted alphabetically, excluding hash.
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()) if k != "hash")

    # Secret key is SHA-256 of the bot token (raw bytes, not hex-encoded).
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_hash, received_hash)


def create_jwt(telegram_id: int, secret: str, ttl_seconds: int = 86400) -> str:
    """Issue a signed JWT for the given Telegram user.

    Claims: ``sub`` = str(telegram_id), ``exp`` = now + ttl_seconds.
    Algorithm: HS256.  Returns the encoded token string.
    """
    now = int(time.time())
    payload = {
        "sub": str(telegram_id),
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: str) -> dict:
    """Decode and validate a JWT; return the claims dict on success.

    Raises ``jwt.ExpiredSignatureError`` when the token has expired.
    Raises ``jwt.InvalidTokenError`` (or a subclass) for any other
    validation failure (bad signature, malformed token, etc.).
    """
    return jwt.decode(token, secret, algorithms=["HS256"])


def verify_jwt_token(token: str, secret: str | None = None) -> dict:
    """Verify a JWT token and return its payload.

    Thin wrapper around ``decode_jwt`` for use by FastAPI dependencies.
    When ``secret`` is None the function raises ``jwt.InvalidTokenError``
    so the caller can convert it to an HTTP 401.

    Raises ``jwt.InvalidTokenError`` (or a subclass) on any failure.
    """
    if secret is None:
        raise jwt.InvalidTokenError("JWT secret not configured")
    return decode_jwt(token, secret)
