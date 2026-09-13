"""Exception hierarchy of the Wiser by Feller API client."""

from __future__ import annotations


class WiserError(Exception):
    """Base class for every error raised by the client."""


class WiserConnectionError(WiserError):
    """The gateway could not be reached (DNS, TCP, timeout, malformed HTTP)."""


class NotAWiserGatewayError(WiserConnectionError):
    """The host answered, but not like a Wiser µGateway."""


class WiserApiError(WiserError):
    """The gateway answered with a JSend error envelope."""

    def __init__(self, message: str, path: str = "") -> None:
        """Store the gateway message and the request path."""
        super().__init__(message)
        self.message = message
        self.path = path

    def __str__(self) -> str:
        """Render as `message (path)`."""
        return f"{self.message} ({self.path})" if self.path else self.message


class UnauthorizedError(WiserApiError):
    """The token is unknown to the gateway ("unauthorized user")."""


class ApiLockedError(WiserApiError):
    """A token is required but none (or an invalid one) was sent ("api is locked")."""


class SourceNotFoundError(WiserApiError):
    """Claim: the `source` account does not exist ("... not a directory")."""


class NoSiteInfoError(WiserApiError):
    """Claim: the gateway has no site information yet ("no site info")."""


class ClaimTimeoutError(WiserApiError):
    """Claim: nobody pressed a button on the gateway within the time window."""


class RequestFailedError(WiserApiError):
    """Any other JSend error."""


class WebsocketAuthError(WiserError):
    """The websocket handshake was rejected because of the token."""
