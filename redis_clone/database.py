"""
In-memory key-value store.

Encapsulates all storage and retrieval logic so that the networking
and command-routing layers have no direct access to the underlying dict.
"""
from __future__ import annotations


class Database:
    """Simple in-memory string → string store."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        """Persist *value* under *key*, overwriting any previous entry."""
        self._store[key] = value

    def get(self, key: str) -> str | None:
        """Return the value for *key*, or ``None`` if the key does not exist."""
        return self._store.get(key)
