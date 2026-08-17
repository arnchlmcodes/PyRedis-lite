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


# ------------------------------------------------------------------
# NX / XX / GET flag tests
# ------------------------------------------------------------------


class TestDatabaseNXXXGET:
    """Tests for SET NX, XX, and GET flags."""

    def setup_method(self):
        self.db = Database()

    # -- NX (only set if key does NOT exist) -----------------------

    def test_nx_sets_when_key_missing(self):
        result = self.db.set("k", "v", nx=True)
        assert result is None  # success, no GET
        assert self.db.get("k") == "v"

    def test_nx_rejected_when_key_exists(self):
        self.db.set("k", "old")
        result = self.db.set("k", "new", nx=True)
        assert result is Database._NOT_SET
        # Value unchanged
        assert self.db.get("k") == "old"

    def test_nx_with_ex_sets_ttl_on_success(self):
        """NX + EX should compose: set both value and TTL."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            result = self.db.set("k", "v", nx=True, ex=10)
            assert result is None  # success

            mock_time.time.return_value = 1009.0
            assert self.db.get("k") == "v"

            mock_time.time.return_value = 1011.0
            assert self.db.get("k") is None

    def test_nx_treats_expired_key_as_missing(self):
        """An expired key should be treated as non-existent for NX."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "old", ex=1)

            mock_time.time.return_value = 1002.0
            result = self.db.set("k", "new", nx=True)
            assert result is None  # success – expired key doesn't block
            assert self.db.get("k") == "new"

    # -- XX (only set if key DOES exist) ---------------------------

    def test_xx_sets_when_key_exists(self):
        self.db.set("k", "old")
        result = self.db.set("k", "new", xx=True)
        assert result is None
        assert self.db.get("k") == "new"

    def test_xx_rejected_when_key_missing(self):
        result = self.db.set("k", "v", xx=True)
        assert result is Database._NOT_SET
        assert self.db.get("k") is None

    def test_xx_with_ex_sets_new_ttl(self):
        """XX + EX should update the value *and* set a new TTL."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "old")  # no TTL

            self.db.set("k", "new", xx=True, ex=5)

            mock_time.time.return_value = 1004.0
            assert self.db.get("k") == "new"

            mock_time.time.return_value = 1006.0
            assert self.db.get("k") is None

    # -- GET (return old value) ------------------------------------

    def test_get_flag_returns_old_value(self):
        self.db.set("k", "old")
        result = self.db.set("k", "new", get=True)
        assert result == "old"
        assert self.db.get("k") == "new"

    def test_get_flag_returns_none_when_no_old_value(self):
        result = self.db.set("k", "v", get=True)
        assert result is None
        assert self.db.get("k") == "v"

    def test_nx_with_get_returns_old_on_rejection(self):
        """SET k v NX GET when key exists → returns old value, no write."""
        self.db.set("k", "old")
        result = self.db.set("k", "new", nx=True, get=True)
        assert result == "old"
        assert self.db.get("k") == "old"  # unchanged

    def test_nx_with_get_returns_none_on_success(self):
        """SET k v NX GET when key missing → returns None, writes."""
        result = self.db.set("k", "v", nx=True, get=True)
        assert result is None
        assert self.db.get("k") == "v"

    def test_xx_with_get_returns_old_on_success(self):
        """SET k v XX GET when key exists → returns old value, writes."""
        self.db.set("k", "old")
        result = self.db.set("k", "new", xx=True, get=True)
        assert result == "old"
        assert self.db.get("k") == "new"

    def test_xx_with_get_returns_none_on_rejection(self):
        """SET k v XX GET when key missing → returns None, no write."""
        result = self.db.set("k", "v", xx=True, get=True)
        assert result is None
        assert self.db.get("k") is None


# ------------------------------------------------------------------
# DEL command tests
# ------------------------------------------------------------------


class TestDatabaseDEL:
    """Tests for the Database.delete() method."""

    def setup_method(self):
        self.db = Database()

    def test_del_single_existing_key(self):
        self.db.set("k", "v")
        assert self.db.delete("k") == 1
        assert self.db.get("k") is None

    def test_del_nonexistent_key_returns_zero(self):
        assert self.db.delete("ghost") == 0

    def test_del_multiple_keys(self):
        self.db.set("a", "1")
        self.db.set("b", "2")
        self.db.set("c", "3")
        assert self.db.delete("a", "b", "c") == 3
        assert self.db.get("a") is None
        assert self.db.get("b") is None
        assert self.db.get("c") is None

    def test_del_mix_of_existing_and_missing(self):
        self.db.set("a", "1")
        self.db.set("c", "3")
        assert self.db.delete("a", "b", "c") == 2

    def test_del_clears_ttl(self):
        """DEL should also remove the expiry metadata."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", ex=100)
            self.db.delete("k")
            assert "k" not in self.db._expiry

    def test_del_does_not_count_expired_key(self):
        """An already-expired key should not be counted as deleted."""
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.set("k", "v", ex=1)

            mock_time.time.return_value = 1002.0
            assert self.db.delete("k") == 0
