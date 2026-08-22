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


# ------------------------------------------------------------------
# List Operations & WRONGTYPE tests
# ------------------------------------------------------------------
from redis_clone.database import WrongTypeError


class TestDatabaseLists:
    def setup_method(self):
        self.db = Database()

    # -- LPUSH / RPUSH ---------------------------------------------

    def test_lpush_single_and_multiple(self):
        assert self.db.lpush("mylist", "world") == 1
        assert self.db.lpush("mylist", "hello") == 2
        # Head-pushing multiple values at once: values pushed one by one to head
        assert self.db.lpush("mylist", "a", "b") == 4
        # Order should be ["b", "a", "hello", "world"]
        assert self.db.lrange("mylist", 0, -1) == ["b", "a", "hello", "world"]

    def test_rpush_single_and_multiple(self):
        assert self.db.rpush("mylist", "hello") == 1
        assert self.db.rpush("mylist", "world") == 2
        assert self.db.rpush("mylist", "foo", "bar") == 4
        assert self.db.lrange("mylist", 0, -1) == ["hello", "world", "foo", "bar"]

    # -- LRANGE ----------------------------------------------------

    def test_lrange_positive_indices(self):
        self.db.rpush("mylist", "a", "b", "c", "d")
        assert self.db.lrange("mylist", 0, 0) == ["a"]
        assert self.db.lrange("mylist", 0, 1) == ["a", "b"]
        assert self.db.lrange("mylist", 1, 2) == ["b", "c"]
        assert self.db.lrange("mylist", 0, 3) == ["a", "b", "c", "d"]

    def test_lrange_negative_indices(self):
        self.db.rpush("mylist", "one", "two", "three", "four", "five")
        assert self.db.lrange("mylist", 0, -1) == ["one", "two", "three", "four", "five"]
        assert self.db.lrange("mylist", -3, -1) == ["three", "four", "five"]
        assert self.db.lrange("mylist", -2, -1) == ["four", "five"]
        assert self.db.lrange("mylist", -100, 100) == ["one", "two", "three", "four", "five"]

    def test_lrange_out_of_bounds_and_inverted(self):
        self.db.rpush("mylist", "a", "b", "c")
        assert self.db.lrange("mylist", 5, 10) == []
        assert self.db.lrange("mylist", 2, 1) == []
        assert self.db.lrange("mylist", -1, -2) == []

    def test_lrange_nonexistent_key_returns_empty_list(self):
        assert self.db.lrange("nonexistent", 0, -1) == []

    # -- LLEN ------------------------------------------------------

    def test_llen_existing_and_nonexistent(self):
        assert self.db.llen("missing") == 0
        self.db.rpush("mylist", "a", "b", "c")
        assert self.db.llen("mylist") == 3

    # -- LPOP / RPOP -----------------------------------------------

    def test_lpop_single(self):
        self.db.rpush("mylist", "a", "b", "c")
        assert self.db.lpop("mylist") == "a"
        assert self.db.lpop("mylist") == "b"
        assert self.db.lpop("mylist") == "c"
        assert self.db.lpop("mylist") is None
        # Once empty, key is removed
        assert not self.db.exists("mylist")

    def test_rpop_single(self):
        self.db.rpush("mylist", "a", "b", "c")
        assert self.db.rpop("mylist") == "c"
        assert self.db.rpop("mylist") == "b"
        assert self.db.rpop("mylist") == "a"
        assert self.db.rpop("mylist") is None
        assert not self.db.exists("mylist")

    def test_lpop_with_count(self):
        self.db.rpush("mylist", "a", "b", "c", "d")
        assert self.db.lpop("mylist", count=2) == ["a", "b"]
        assert self.db.lrange("mylist", 0, -1) == ["c", "d"]
        assert self.db.lpop("mylist", count=10) == ["c", "d"]
        assert self.db.lpop("mylist", count=2) is None

    def test_rpop_with_count(self):
        self.db.rpush("mylist", "a", "b", "c", "d")
        assert self.db.rpop("mylist", count=2) == ["d", "c"]
        assert self.db.lrange("mylist", 0, -1) == ["a", "b"]
        assert self.db.rpop("mylist", count=10) == ["b", "a"]
        assert self.db.rpop("mylist", count=2) is None

    # -- DEL and Expiry on Lists -----------------------------------

    def test_del_on_list(self):
        self.db.rpush("mylist", "a", "b")
        assert self.db.delete("mylist") == 1
        assert not self.db.exists("mylist")
        assert self.db.llen("mylist") == 0

    def test_list_lazy_expiry(self):
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.rpush("mylist", "a")
            self.db._expiry["mylist"] = 1005.0

            mock_time.time.return_value = 1004.0
            assert self.db.llen("mylist") == 1

            mock_time.time.return_value = 1006.0
            assert self.db.llen("mylist") == 0
            assert not self.db.exists("mylist")


class TestDatabaseWrongType:
    def setup_method(self):
        self.db = Database()

    def test_string_op_on_list_raises_wrongtype(self):
        self.db.rpush("mylist", "a", "b")
        with pytest.raises(WrongTypeError):
            self.db.set("mylist", "val")
        with pytest.raises(WrongTypeError):
            self.db.get("mylist")

    def test_list_op_on_string_raises_wrongtype(self):
        self.db.set("mystring", "hello")
        with pytest.raises(WrongTypeError):
            self.db.lpush("mystring", "a")
        with pytest.raises(WrongTypeError):
            self.db.rpush("mystring", "a")
        with pytest.raises(WrongTypeError):
            self.db.lrange("mystring", 0, -1)
        with pytest.raises(WrongTypeError):
            self.db.llen("mystring")
        with pytest.raises(WrongTypeError):
            self.db.lpop("mystring")
        with pytest.raises(WrongTypeError):
            self.db.rpop("mystring")

    def test_hash_op_on_string_raises_wrongtype(self):
        self.db.set("mystr", "hello")
        with pytest.raises(WrongTypeError):
            self.db.hset("mystr", "f1", "v1")
        with pytest.raises(WrongTypeError):
            self.db.hget("mystr", "f1")
        with pytest.raises(WrongTypeError):
            self.db.hgetall("mystr")
        with pytest.raises(WrongTypeError):
            self.db.hdel("mystr", "f1")
        with pytest.raises(WrongTypeError):
            self.db.hexists("mystr", "f1")
        with pytest.raises(WrongTypeError):
            self.db.hlen("mystr")

    def test_hash_op_on_list_raises_wrongtype(self):
        self.db.rpush("mylist", "item")
        with pytest.raises(WrongTypeError):
            self.db.hset("mylist", "f1", "v1")
        with pytest.raises(WrongTypeError):
            self.db.hget("mylist", "f1")
        with pytest.raises(WrongTypeError):
            self.db.hgetall("mylist")
        with pytest.raises(WrongTypeError):
            self.db.hdel("mylist", "f1")
        with pytest.raises(WrongTypeError):
            self.db.hexists("mylist", "f1")
        with pytest.raises(WrongTypeError):
            self.db.hlen("mylist")

    def test_string_and_list_ops_on_hash_raise_wrongtype(self):
        self.db.hset("myhash", "f1", "v1")
        with pytest.raises(WrongTypeError):
            self.db.set("myhash", "strval")
        with pytest.raises(WrongTypeError):
            self.db.get("myhash")
        with pytest.raises(WrongTypeError):
            self.db.lpush("myhash", "a")
        with pytest.raises(WrongTypeError):
            self.db.rpush("myhash", "a")
        with pytest.raises(WrongTypeError):
            self.db.lrange("myhash", 0, -1)
        with pytest.raises(WrongTypeError):
            self.db.llen("myhash")
        with pytest.raises(WrongTypeError):
            self.db.lpop("myhash")
        with pytest.raises(WrongTypeError):
            self.db.rpop("myhash")


# ------------------------------------------------------------------
# Hash Operations tests
# ------------------------------------------------------------------


class TestDatabaseHashes:
    def setup_method(self):
        self.db = Database()

    def test_hset_single_and_multi_field(self):
        # Setting a new field returns 1
        assert self.db.hset("myhash", "f1", "v1") == 1
        # Updating an existing field returns 0
        assert self.db.hset("myhash", "f1", "v1_updated") == 0
        assert self.db.hget("myhash", "f1") == "v1_updated"

        # Multi-field: 1 update, 2 new fields -> returns 2
        assert self.db.hset("myhash", "f1", "new_v1", "f2", "v2", "f3", "v3") == 2
        assert self.db.hget("myhash", "f1") == "new_v1"
        assert self.db.hget("myhash", "f2") == "v2"
        assert self.db.hget("myhash", "f3") == "v3"

    def test_hset_odd_arguments_raises_value_error(self):
        with pytest.raises(ValueError):
            self.db.hset("myhash", "f1")

    def test_hget_missing_key_and_missing_field(self):
        assert self.db.hget("missing_key", "f1") is None
        self.db.hset("myhash", "f1", "v1")
        assert self.db.hget("myhash", "f2") is None

    def test_hgetall(self):
        assert self.db.hgetall("missing") == []
        self.db.hset("user:1", "name", "alice", "age", "30")
        items = self.db.hgetall("user:1")
        # Items is flat [f1, v1, f2, v2, ...]
        assert len(items) == 4
        d = dict(zip(items[0::2], items[1::2]))
        assert d == {"name": "alice", "age": "30"}

    def test_hdel(self):
        self.db.hset("myhash", "f1", "v1", "f2", "v2", "f3", "v3")
        # Delete existing and missing field
        assert self.db.hdel("myhash", "f1", "f4") == 1
        assert self.db.hget("myhash", "f1") is None
        assert self.db.hexists("myhash", "f1") is False

        # Deleting all remaining fields removes the hash key
        assert self.db.hdel("myhash", "f2", "f3") == 2
        assert not self.db.exists("myhash")
        assert self.db.hdel("myhash", "f2") == 0

    def test_hexists(self):
        assert self.db.hexists("missing", "f1") is False
        self.db.hset("myhash", "f1", "v1")
        assert self.db.hexists("myhash", "f1") is True
        assert self.db.hexists("myhash", "other") is False

    def test_hlen(self):
        assert self.db.hlen("missing") == 0
        self.db.hset("myhash", "f1", "v1", "f2", "v2")
        assert self.db.hlen("myhash") == 2

    def test_del_on_hash(self):
        self.db.hset("myhash", "f1", "v1", "f2", "v2")
        assert self.db.delete("myhash") == 1
        assert not self.db.exists("myhash")
        assert self.db.hlen("myhash") == 0

    def test_hash_lazy_expiry(self):
        with patch("redis_clone.database.time") as mock_time:
            mock_time.time.return_value = 1000.0
            self.db.hset("myhash", "f1", "v1")
            self.db._expiry["myhash"] = 1005.0

            mock_time.time.return_value = 1004.0
            assert self.db.hlen("myhash") == 1

            mock_time.time.return_value = 1006.0
            assert self.db.hlen("myhash") == 0
            assert not self.db.exists("myhash")


