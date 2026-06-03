"""Unit tests for web/auth.py — Telegram login verification and JWT utilities."""

import hashlib
import hmac
import time

import jwt
import pytest

from web.auth import create_jwt, decode_jwt, verify_telegram_login  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOT_TOKEN = "1234567890:AAFakeTokenForTestingPurposesOnly"
JWT_SECRET = "test-super-secret-key-for-unit-tests"
TELEGRAM_ID = 123456789


def _make_valid_payload(bot_token: str = BOT_TOKEN, age_seconds: int = 0) -> dict:
    """Build a correctly signed Telegram Login Widget payload."""
    auth_date = int(time.time()) - age_seconds
    data: dict = {
        "id": str(TELEGRAM_ID),
        "first_name": "Test",
        "auth_date": str(auth_date),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    data["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return data


# ---------------------------------------------------------------------------
# verify_telegram_login
# ---------------------------------------------------------------------------


def test_verify_telegram_login_valid_payload_returns_true() -> None:
    """Returns True for a correctly constructed, fresh Telegram login payload."""
    payload = _make_valid_payload()
    assert verify_telegram_login(payload, BOT_TOKEN) is True


def test_verify_telegram_login_tampered_hash_returns_false() -> None:
    """Returns False when the hash field has been tampered with."""
    payload = _make_valid_payload()
    payload["hash"] = "deadbeef" * 8  # wrong hash, correct length
    assert verify_telegram_login(payload, BOT_TOKEN) is False


def test_verify_telegram_login_wrong_bot_token_returns_false() -> None:
    """Returns False when verified against a different bot token."""
    payload = _make_valid_payload()
    assert verify_telegram_login(payload, "9999999999:AnotherFakeBotToken") is False


def test_verify_telegram_login_expired_auth_date_returns_false() -> None:
    """Returns False when auth_date is older than 86400 seconds."""
    payload = _make_valid_payload(age_seconds=86401)
    assert verify_telegram_login(payload, BOT_TOKEN) is False


def test_verify_telegram_login_exactly_at_boundary_returns_false() -> None:
    """Returns False when auth_date is exactly 86400 seconds old (boundary is exclusive)."""
    payload = _make_valid_payload(age_seconds=86400)
    assert verify_telegram_login(payload, BOT_TOKEN) is False


def test_verify_telegram_login_missing_hash_returns_false() -> None:
    """Returns False when the hash field is absent."""
    payload = _make_valid_payload()
    del payload["hash"]
    assert verify_telegram_login(payload, BOT_TOKEN) is False


def test_verify_telegram_login_missing_auth_date_returns_false() -> None:
    """Returns False when the auth_date field is absent."""
    payload = _make_valid_payload()
    del payload["auth_date"]
    assert verify_telegram_login(payload, BOT_TOKEN) is False


def test_verify_telegram_login_invalid_auth_date_returns_false() -> None:
    """Returns False when auth_date is not a valid integer."""
    payload = _make_valid_payload()
    payload["auth_date"] = "not-a-number"
    assert verify_telegram_login(payload, BOT_TOKEN) is False


def test_verify_telegram_login_extra_field_changes_hash() -> None:
    """Adding an extra field to a valid payload invalidates the hash."""
    payload = _make_valid_payload()
    payload["username"] = "injected"  # not part of original check string
    assert verify_telegram_login(payload, BOT_TOKEN) is False


# ---------------------------------------------------------------------------
# create_jwt + decode_jwt round-trip
# ---------------------------------------------------------------------------


def test_create_and_decode_jwt_round_trip() -> None:
    """create_jwt and decode_jwt round-trip correctly for a valid token."""
    token = create_jwt(TELEGRAM_ID, JWT_SECRET)
    claims = decode_jwt(token, JWT_SECRET)

    assert claims["sub"] == str(TELEGRAM_ID)
    assert "exp" in claims


def test_create_jwt_returns_string() -> None:
    """create_jwt returns a non-empty string."""
    token = create_jwt(TELEGRAM_ID, JWT_SECRET)
    assert isinstance(token, str)
    assert len(token) > 0


def test_create_jwt_custom_ttl() -> None:
    """create_jwt respects a custom ttl_seconds value."""
    ttl = 3600
    before = int(time.time())
    token = create_jwt(TELEGRAM_ID, JWT_SECRET, ttl_seconds=ttl)
    after = int(time.time())

    claims = decode_jwt(token, JWT_SECRET)
    # exp should be within [before+ttl, after+ttl]
    assert before + ttl <= claims["exp"] <= after + ttl


def test_decode_jwt_wrong_secret_raises() -> None:
    """decode_jwt raises jwt.InvalidTokenError when the secret is wrong."""
    token = create_jwt(TELEGRAM_ID, JWT_SECRET)
    with pytest.raises(jwt.InvalidTokenError):
        decode_jwt(token, "wrong-secret")


def test_decode_jwt_expired_token_raises() -> None:
    """decode_jwt raises jwt.ExpiredSignatureError for an expired token."""
    # Create a token that expired 10 seconds ago.
    token = create_jwt(TELEGRAM_ID, JWT_SECRET, ttl_seconds=-10)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_jwt(token, JWT_SECRET)


def test_decode_jwt_malformed_token_raises() -> None:
    """decode_jwt raises jwt.InvalidTokenError for a malformed token string."""
    with pytest.raises(jwt.InvalidTokenError):
        decode_jwt("this.is.not.a.jwt", JWT_SECRET)


def test_decode_jwt_empty_token_raises() -> None:
    """decode_jwt raises jwt.InvalidTokenError for an empty string."""
    with pytest.raises(jwt.InvalidTokenError):
        decode_jwt("", JWT_SECRET)
