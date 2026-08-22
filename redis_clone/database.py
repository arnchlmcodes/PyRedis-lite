"""
In-memory key-value store.

Encapsulates all storage and retrieval logic so that the networking
and command-routing layers have no direct access to the underlying dict.
"""
from __future__ import annotations

import time


class WrongTypeError(Exception):
    """Raised when an operation is attempted against a key holding a different data type."""


class Database:
    """In-memory key-value store with string, list, and TTL support."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._list_store: dict[str, list[str]] = {}
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
        """Remove *key* from stores if it has expired.

        Returns ``True`` if the key was evicted.
        """
        if self._is_expired(key):
            self._store.pop(key, None)
            self._list_store.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    # ------------------------------------------------------------------
    # String Operations
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
        self._evict_if_expired(key)

        if key in self._list_store:
            raise WrongTypeError(
                "Operation against a key holding the wrong kind of value"
            )

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

        old_expiry = self._expiry.get(key)

        self._store[key] = value

        if new_expiry is not None:
            self._expiry[key] = new_expiry
        elif keepttl and old_expiry is not None:
            self._expiry[key] = old_expiry
        else:
            self._expiry.pop(key, None)

        return old_value if get else None

    def get(self, key: str) -> str | None:
        """Return the value for *key*, or ``None`` if the key does not exist
        or has expired (lazy eviction).
        """
        if self._evict_if_expired(key):
            return None
        if key in self._list_store:
            raise WrongTypeError(
                "Operation against a key holding the wrong kind of value"
            )
        return self._store.get(key)

    # ------------------------------------------------------------------
    # List Operations
    # ------------------------------------------------------------------

    def lpush(self, key: str, *values: str) -> int:
        """Insert elements at the head of the list stored at *key*.

        Creates the list if it doesn't exist.
        Returns the length of the list after the push operation.
        """
        self._evict_if_expired(key)
        if key in self._store:
            raise WrongTypeError(
                "Operation against a key holding the wrong kind of value"
            )
        if not values:
            return len(self._list_store.get(key, []))

        lst = self._list_store.setdefault(key, [])
        for val in values:
            lst.insert(0, val)
        return len(lst)

    def rpush(self, key: str, *values: str) -> int:
        """Append elements to the tail of the list stored at *key*.

        Creates the list if it doesn't exist.
        Returns the length of the list after the push operation.
        """
        self._evict_if_expired(key)
        if key in self._store:
            raise WrongTypeError(
                "Operation against a key holding the wrong kind of value"
            )
        if not values:
            return len(self._list_store.get(key, []))

        lst = self._list_store.setdefault(key, [])
        lst.extend(values)
        return len(lst)

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        """Return a slice of elements from the list at *key* between *start* and *stop* (inclusive).

        Supports negative offsets (e.g. -1 for last element).
        """
        self._evict_if_expired(key)
        if key in self._store:
            raise WrongTypeError(
                "Operation against a key holding the wrong kind of value"
            )
        if key not in self._list_store:
            return []

        lst = self._list_store[key]
        n = len(lst)
        if n == 0:
            return []

        # Normalize negative indices
        if start < 0:
            start = n + start
        if stop < 0:
            stop = n + stop

        # Clamp boundaries
        if start < 0:
            start = 0
        if stop >= n:
            stop = n - 1

        if start > stop or start >= n:
            return []

        return list(lst[start : stop + 1])

    def llen(self, key: str) -> int:
        """Return the length of the list stored at *key*."""
        self._evict_if_expired(key)
        if key in self._store:
            raise WrongTypeError(
                "Operation against a key holding the wrong kind of value"
            )
        return len(self._list_store.get(key, []))

    def lpop(self, key: str, count: int | None = None) -> list[str] | str | None:
        """Remove and return elements from the head of the list at *key*.

        If count is None, returns a single string or None.
        If count is provided, returns a list of strings (or None if key absent).
        """
        self._evict_if_expired(key)
        if key in self._store:
            raise WrongTypeError(
                "Operation against a key holding the wrong kind of value"
            )
        if key not in self._list_store:
            return None

        lst = self._list_store[key]
        if count is None:
            if not lst:
                self._list_store.pop(key, None)
                self._expiry.pop(key, None)
                return None
            val = lst.pop(0)
            if not lst:
                self._list_store.pop(key, None)
                self._expiry.pop(key, None)
            return val

        # count is specified
        popped: list[str] = []
        for _ in range(count):
            if not lst:
                break
            popped.append(lst.pop(0))
        if not lst:
            self._list_store.pop(key, None)
            self._expiry.pop(key, None)
        return popped

    def rpop(self, key: str, count: int | None = None) -> list[str] | str | None:
        """Remove and return elements from the tail of the list at *key*.

        If count is None, returns a single string or None.
        If count is provided, returns a list of strings (or None if key absent).
        """
        self._evict_if_expired(key)
        if key in self._store:
            raise WrongTypeError(
                "Operation against a key holding the wrong kind of value"
            )
        if key not in self._list_store:
            return None

        lst = self._list_store[key]
        if count is None:
            if not lst:
                self._list_store.pop(key, None)
                self._expiry.pop(key, None)
                return None
            val = lst.pop()
            if not lst:
                self._list_store.pop(key, None)
                self._expiry.pop(key, None)
            return val

        popped: list[str] = []
        for _ in range(count):
            if not lst:
                break
            popped.append(lst.pop())
        if not lst:
            self._list_store.pop(key, None)
            self._expiry.pop(key, None)
        return popped

    # ------------------------------------------------------------------
    # Generic Key Operations
    # ------------------------------------------------------------------

    def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists and has not expired."""
        self._evict_if_expired(key)
        return (key in self._store) or (key in self._list_store)

    def delete(self, *keys: str) -> int:
        """Remove *keys* from the store. Return the number of keys that
        were actually present (and thus removed).
        """
        count = 0
        for key in keys:
            self._evict_if_expired(key)
            removed = False
            if key in self._store:
                del self._store[key]
                removed = True
            if key in self._list_store:
                del self._list_store[key]
                removed = True
            if removed:
                self._expiry.pop(key, None)
                count += 1
        return count
