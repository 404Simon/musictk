"""Shared retry policy for resilient external HTTP services."""

from __future__ import annotations

import random
from contextlib import suppress
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration and delay calculation for transient HTTP failures."""

    max_attempts: int = 4
    retryable_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    base_delay: float = 2.0
    max_delay: float = 30.0
    jitter: float = 0.5

    def delay(self, attempt: int, retry_after: str | None = None) -> float:
        """Return bounded backoff, never shortened by Retry-After."""
        exponential_delay = self.base_delay * 2 ** (attempt - 1)
        backoff = exponential_delay + random.uniform(0.0, self.jitter)

        if retry_after is not None:
            with suppress(ValueError):
                backoff = max(backoff, float(retry_after))

        return float(min(max(backoff, 0.0), self.max_delay))


TRANSIENT_HTTP_RETRY = RetryPolicy()
