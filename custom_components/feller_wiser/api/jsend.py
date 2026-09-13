"""JSend envelope handling for the µGateway REST API.

Every REST response looks like ``{"status": "success", "data": ...}`` or
``{"status": "error", "message": "..."}`` and is delivered with HTTP 200 either way.
"""

from __future__ import annotations

from typing import Any

from .const import MSG_API_LOCKED, MSG_NO_SITE_INFO, MSG_SOURCE_NOT_FOUND, MSG_UNAUTHORIZED
from .errors import (
    ApiLockedError,
    NoSiteInfoError,
    NotAWiserGatewayError,
    RequestFailedError,
    SourceNotFoundError,
    UnauthorizedError,
    WiserApiError,
)


def unwrap(payload: Any, path: str) -> Any:
    """Return the ``data`` part of a JSend payload or raise the matching error."""
    if not isinstance(payload, dict) or "status" not in payload:
        raise NotAWiserGatewayError(f"Response from {path} is not a JSend envelope")
    status = payload.get("status")
    if status == "success":
        return payload.get("data")
    message = str(payload.get("message", "unknown error"))
    raise error_for_message(message, path)


def error_for_message(message: str, path: str) -> WiserApiError:
    """Map a JSend error message to the most specific exception type."""
    lowered = message.lower()
    if MSG_API_LOCKED in lowered:
        return ApiLockedError(message, path)
    if MSG_UNAUTHORIZED in lowered:
        return UnauthorizedError(message, path)
    if MSG_SOURCE_NOT_FOUND in lowered:
        return SourceNotFoundError(message, path)
    if MSG_NO_SITE_INFO in lowered:
        return NoSiteInfoError(message, path)
    return RequestFailedError(message, path)
