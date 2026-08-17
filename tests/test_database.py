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


# ------------------------------------------------------------------
# TTL / Expiry tests
# ------------------------------------------------------------------
from unittest.mock import patch


class TestDatabaseTTL:
    """Tests for TTL support (EX, PX, EXAT, PXAT, KEEPTTL)."""

    def setup_method(self):
        self.db = Database()

    # -- EX (seconds, relative) ------------------------------------

    def test_set_with_ex_returns_value_before_expiry(self):
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", ex=10)

            # Still within the 10-second window
            mock_time.time.return_value = 1009.0
            assert self.db.get("k") == "v"

    def test_set_with_ex_expires_after_deadline(self):
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", ex=10)

            # Past the deadline
            mock_time.time.return_value = 1011.0
            assert self.db.get("k") is None

    # -- PX (milliseconds, relative) -------------------------------

    def test_set_with_px_returns_value_before_expiry(self):
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", px=5000)  # 5 seconds

            mock_time.time.return_value = 1004.0
            assert self.db.get("k") == "v"

    def test_set_with_px_expires_after_deadline(self):
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", px=5000)

            mock_time.time.return_value = 1006.0
            assert self.db.get("k") is None

    # -- Expired key returns None (nil) ----------------------------

    def test_expired_key_returns_none_on_get(self):
        """A key whose TTL has elapsed should return None (RESP null)."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("ephemeral", "data", ex=1)

            mock_time.time.return_value = 1002.0
            assert self.db.get("ephemeral") is None

    def test_expired_key_is_evicted_from_store(self):
        """After lazy eviction the key should no longer appear in _store."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", ex=1)

            mock_time.time.return_value = 1002.0
            self.db.get("k")  # triggers eviction
            assert "k" not in self.db._store
            assert "k" not in self.db._expiry

    # -- KEEPTTL ---------------------------------------------------

    def test_keepttl_preserves_ttl_across_overwrite(self):
        """SET with KEEPTTL should keep the original expiry deadline."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v1", ex=10)  # expires at 1010

            # Overwrite the value but preserve TTL
            mock_time.time.return_value = 1005.0
            self.db.set("k", "v2", keepttl=True)

            # Value updated, still before expiry
            mock_time.time.return_value = 1009.0
            assert self.db.get("k") == "v2"

            # Past the *original* expiry → gone
            mock_time.time.return_value = 1011.0
            assert self.db.get("k") is None

    # -- Bare SET clears prior TTL ---------------------------------

    def test_bare_set_without_keepttl_clears_prior_ttl(self):
        """A plain SET (no TTL option, no KEEPTTL) must drop the old TTL."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v1", ex=5)  # expires at 1005

            # Overwrite without KEEPTTL
            mock_time.time.return_value = 1003.0
            self.db.set("k", "v2")

            # Well past the old expiry – key should still exist
            mock_time.time.return_value = 2000.0
            assert self.db.get("k") == "v2"

    # -- EXAT (absolute timestamp, seconds) ------------------------

    def test_set_with_exat(self):
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", exat=1500)

            mock_time.time.return_value = 1499.0
            assert self.db.get("k") == "v"

            mock_time.time.return_value = 1501.0
            assert self.db.get("k") is None

    # -- PXAT (absolute timestamp, milliseconds) -------------------

    def test_set_with_pxat(self):
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", pxat=1_500_000)  # 1500.0 seconds

            mock_time.time.return_value = 1499.0
            assert self.db.get("k") == "v"

            mock_time.time.return_value = 1501.0
            assert self.db.get("k") is None
