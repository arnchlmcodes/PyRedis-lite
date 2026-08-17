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

    # Sentinel used to distinguish "SET was rejected by NX/XX" from
    # "SET succeeded and there was no old value (None)".
    _NOT_SET: object = object()

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
        nx: bool = False,
        xx: bool = False,
        get: bool = False,
    ) -> str | None | object:
        """Persist *value* under *key*, with optional conditions and TTL.

        Condition flags:
        * *nx*  – only set if the key does **not** already exist.
        * *xx*  – only set if the key **does** already exist.
        * *get* – return the old value (or ``None``) regardless of outcome.

        TTL options (mutually exclusive – first match wins):
        * *ex*   – expire in *ex* seconds (relative).
        * *px*   – expire in *px* milliseconds (relative).
        * *exat* – expire at Unix-timestamp *exat* (seconds, absolute).
        * *pxat* – expire at Unix-timestamp *pxat* (milliseconds, absolute).
        * *keepttl* – preserve the existing TTL if one was set.

        When none of the above are given, any prior TTL on *key* is cleared.

        Returns:
        * When *get* is ``True``: the previous value (``str`` or ``None``).
        * When NX/XX condition fails and *get* is ``False``:
          the ``Database._NOT_SET`` sentinel.
        * Otherwise: ``None`` (success, no GET).
        """
        # Lazy-evict before evaluating conditions so that an expired key
        # is treated as non-existent.
        self._evict_if_expired(key)

        key_exists = key in self._store
        old_value: str | None = self._store.get(key)

        # NX / XX guards
        if nx and key_exists:
            return old_value if get else Database._NOT_SET
        if xx and not key_exists:
            return old_value if get else Database._NOT_SET

        # --- perform the write ---

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

        return old_value if get else None

    def get(self, key: str) -> str | None:
        """Return the value for *key*, or ``None`` if the key does not exist
        or has expired (lazy eviction).
        """
        if self._evict_if_expired(key):
            return None
        return self._store.get(key)

    def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists and has not expired."""
        self._evict_if_expired(key)
        return key in self._store

    def delete(self, *keys: str) -> int:
        """Remove *keys* from the store. Return the number of keys that
        were actually present (and thus removed).
        """
        count = 0
        for key in keys:
            # Don't count already-expired keys as "deleted".
            self._evict_if_expired(key)
            if key in self._store:
                del self._store[key]
                self._expiry.pop(key, None)
                count += 1
        return count
