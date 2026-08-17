"""
In-memory key-value store.

Encapsulates all storage and retrieval logic so that the networking
and command-routing layers have no direct access to the underlying dict.
"""
from __future__ import annotations

import time


class Database:
    """Simple in-memory string → string store with optional TTL support."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._expiry: dict[str, float] = {}  # key → absolute epoch (seconds)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_expired(self, key: str) -> bool:
        """Return ``True`` if *key* has an expiry that is in the past."""
        exp = self._expiry.get(key)
        if exp is None:
            return False
        return time.time() > exp

    def _evict_if_expired(self, key: str) -> bool:
        """Remove *key* from both stores if it has expired.

        Returns ``True`` if the key was evicted.
        """
        if self._is_expired(key):
            self._store.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        px: int | None = None,
        exat: int | float | None = None,
        pxat: int | float | None = None,
        keepttl: bool = False,
    ) -> None:
        """Persist *value* under *key*, overwriting any previous entry.

        TTL options (mutually exclusive – first match wins):
        * *ex*   – expire in *ex* seconds (relative).
        * *px*   – expire in *px* milliseconds (relative).
        * *exat* – expire at Unix-timestamp *exat* (seconds, absolute).
        * *pxat* – expire at Unix-timestamp *pxat* (milliseconds, absolute).
        * *keepttl* – preserve the existing TTL if one was set.

        When none of the above are given, any prior TTL on *key* is cleared.
        """
        # Determine the new absolute expiry, if any.
        new_expiry: float | None = None
        if ex is not None:
            new_expiry = time.time() + ex
        elif px is not None:
            new_expiry = time.time() + px / 1000.0
        elif exat is not None:
            new_expiry = float(exat)
        elif pxat is not None:
            new_expiry = pxat / 1000.0

        # Capture the old expiry *before* overwriting the value, so that
        # KEEPTTL can re-apply it.
        old_expiry = self._expiry.get(key)

        self._store[key] = value

        if new_expiry is not None:
            # Explicit TTL option supplied → use it.
            self._expiry[key] = new_expiry
        elif keepttl and old_expiry is not None:
            # KEEPTTL: preserve whatever TTL the key already had.
            self._expiry[key] = old_expiry
        else:
            # No TTL option and no KEEPTTL → clear any previous TTL.
            self._expiry.pop(key, None)

    def get(self, key: str) -> str | None:
        """Return the value for *key*, or ``None`` if the key does not exist
        or has expired (lazy eviction).
        """
        if self._evict_if_expired(key):
            return None
        return self._store.get(key)
