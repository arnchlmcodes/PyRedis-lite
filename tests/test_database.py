"""Unit tests for the Database class (no networking)."""
import pytest
from redis_clone.database import Database


class TestDatabase:
    def setup_method(self):
        self.db = Database()

    def test_set_and_get_roundtrip(self):
        self.db.set("key", "value")
        assert self.db.get("key") == "value"

    def test_get_missing_key_returns_none(self):
        assert self.db.get("nonexistent") is None

    def test_overwrite_existing_key(self):
        self.db.set("x", "first")
        self.db.set("x", "second")
        assert self.db.get("x") == "second"

    def test_keys_are_independent(self):
        self.db.set("a", "1")
        self.db.set("b", "2")
        assert self.db.get("a") == "1"
        assert self.db.get("b") == "2"

    def test_empty_string_value(self):
        self.db.set("empty", "")
        assert self.db.get("empty") == ""

    def test_each_instance_has_own_store(self):
        db2 = Database()
        self.db.set("shared_key", "from_db1")
        assert db2.get("shared_key") is None
