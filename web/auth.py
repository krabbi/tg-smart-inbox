"""JWT verification for the web UI companion.

This module is a stub — the full implementation is provided in issue #177.
`verify_jwt_token` will be replaced with a real PyJWT-based check.
"""

from fastapi import HTTPException


def verify_jwt_token(token: str) -> dict:
    """Verify a JWT token and return its payload.

    Raises HTTP 401 for any invalid, expired, or malformed token.
    This stub always raises 401; replaced by the real implementation in #177.
    """
    raise HTTPException(status_code=401, detail="Not authenticated")
