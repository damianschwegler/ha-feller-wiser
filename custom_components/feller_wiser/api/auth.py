"""Onboarding helpers: claim a token with automatic detection of the source account."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .client import WiserClient
from .const import CLAIM_SOURCES
from .errors import SourceNotFoundError


@dataclass(frozen=True, slots=True)
class ClaimResult:
    """Outcome of a successful claim."""

    secret: str
    user: str
    source: str | None


async def claim_with_source_detection(
    client: WiserClient,
    user: str,
    *,
    sources: tuple[str | None, ...] = CLAIM_SOURCES,
    on_attempt: Callable[[str | None], None] | None = None,
) -> ClaimResult:
    """Claim ``user`` copying rooms/names from the first existing source account.

    The gateway rejects a nonexistent ``source`` with an error containing "not a directory";
    we then try the next candidate. ``None`` means a plain claim without copying anything.
    """
    last_error: SourceNotFoundError | None = None
    for source in sources:
        if on_attempt:
            on_attempt(source)
        try:
            account = await client.claim(user, source)
        except SourceNotFoundError as err:
            last_error = err
            continue
        return ClaimResult(secret=account.secret or "", user=account.user, source=source)
    raise last_error or SourceNotFoundError("no claim source worked", "account/claim")
