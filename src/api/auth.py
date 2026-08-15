"""API authentication helpers (Issue #15).

When GTM_API_KEY is configured, all /api/v1 endpoints require the key via the
X-API-Key header. When unset (default), endpoints stay open for local dev.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from ..config import GTM_API_KEY


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Dependency that validates the X-API-Key header when a key is configured."""
    if not GTM_API_KEY:
        # No key configured — API is open (local development / demo).
        return
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    configured = GTM_API_KEY.value or ""
    if not hmac.compare_digest(x_api_key, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
