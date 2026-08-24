"""Integration tests driving PyRedis-lite via the official redis-py client.

Exercises SET, GET, EX, NX, DEL, LPUSH, LRANGE, HSET, and HGETALL
against a live running server instance (local or via Docker Compose).
"""
import os
import threading
import time
import pytest
import redis

from redis_clone.server import Server

TEST_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
TEST_PORT = int(os.environ.get("REDIS_PORT", 6380))


@pytest.fixture(scope="module")
def redis_server():
    """Start local Server in background thread if not connected to external host."""
    if "REDIS_HOST" in os.environ:
        yield None
        return

    server = Server(host=TEST_HOST, port=TEST_PORT)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.15)
    yield server
    server.stop()
    thread.join(timeout=2)


@pytest.fixture
def r(redis_server):
    """Provide a decoded redis-py client connected to the test server."""
    client = redis.Redis(host=TEST_HOST, port=TEST_PORT, decode_responses=True)
    yield client
    client.close()


class TestStringOperationsIntegration:
    """Integration tests for SET, GET, EX, and NX via redis-py."""

    def test_set_and_get(self, r):
        key = "integration:str:basic"
        assert r.set(key, "hello_world") is True
        assert r.get(key) == "hello_world"

    def test_get_nonexistent_key(self, r):
        assert r.get("integration:str:nonexistent") is None

    def test_set_with_ex_ttl_expiration(self, r):
        key = "integration:str:ttl"
        # Set with 1 second expiration
        assert r.set(key, "temp_value", ex=1) is True
        assert r.get(key) == "temp_value"

        # Wait for expiry
        time.sleep(1.2)
        assert r.get(key) is None

    def test_set_with_nx(self, r):
        key = "integration:str:nx"
        r.delete(key)

        # First SET with NX succeeds because key does not exist
        assert r.set(key, "first_val", nx=True) is True
        assert r.get(key) == "first_val"

        # Second SET with NX must be rejected (returns None / False in redis-py)
        assert r.set(key, "second_val", nx=True) is None
        # Value must remain untouched
        assert r.get(key) == "first_val"

    def test_set_with_nx_and_ex_composition(self, r):
        key = "integration:str:nx_ex"
        r.delete(key)

        assert r.set(key, "expiring_nx", nx=True, ex=1) is True
        assert r.get(key) == "expiring_nx"

        # Second write rejected by NX
        assert r.set(key, "blocked", nx=True) is None

        # After expiry, NX should succeed again
        time.sleep(1.2)
        assert r.get(key) is None
        assert r.set(key, "recreated", nx=True) is True
        assert r.get(key) == "recreated"


class TestDeleteOperationsIntegration:
    """Integration tests for DEL command via redis-py."""

    def test_del_single_key(self, r):
        key = "integration:del:single"
        r.set(key, "val")
        assert r.delete(key) == 1
        assert r.get(key) is None

    def test_del_multiple_keys(self, r):
        k1 = "integration:del:m1"
        k2 = "integration:del:m2"
        k3 = "integration:del:m3"
        r.set(k1, "v1")
        r.set(k2, "v2")
        r.set(k3, "v3")

        # Delete 2 existing keys and 1 non-existent key
        deleted_count = r.delete(k1, k2, "integration:del:missing")
        assert deleted_count == 2

        assert r.get(k1) is None
        assert r.get(k2) is None
        assert r.get(k3) == "v3"

    def test_del_nonexistent_returns_zero(self, r):
        assert r.delete("integration:del:ghost") == 0


class TestListOperationsIntegration:
    """Integration tests for LPUSH and LRANGE via redis-py."""

    def test_lpush_and_lrange_full(self, r):
        key = "integration:list:items"
        r.delete(key)

        # Single and multiple elements push
        assert r.lpush(key, "c") == 1
        assert r.lpush(key, "b") == 2
        # Multiple values at once: "a" then "head"
        assert r.lpush(key, "b_prev", "a") == 4

        # Full range: ["a", "b_prev", "b", "c"]
        elements = r.lrange(key, 0, -1)
        assert elements == ["a", "b_prev", "b", "c"]

    def test_lrange_sub_slices_and_negative_offsets(self, r):
        key = "integration:list:slice"
        r.delete(key)
        for val in ["one", "two", "three", "four", "five"]:
            r.rpush(key, val)

        assert r.lrange(key, 0, 1) == ["one", "two"]
        assert r.lrange(key, 2, 3) == ["three", "four"]
        assert r.lrange(key, -2, -1) == ["four", "five"]
        assert r.lrange(key, 10, 20) == []


class TestHashOperationsIntegration:
    """Integration tests for HSET and HGETALL via redis-py."""

    def test_hset_single_and_multi_field(self, r):
        key = "integration:hash:user"
        r.delete(key)

        # Single field set -> 1 newly added
        assert r.hset(key, "name", "alice") == 1
        # Update existing field -> 0 newly added
        assert r.hset(key, "name", "alice_smith") == 0

        # Multi-field via mapping -> returns number of newly added fields
        added = r.hset(key, mapping={"role": "admin", "department": "engineering"})
        assert added == 2

    def test_hgetall_complete(self, r):
        key = "integration:hash:profile"
        r.delete(key)

        data = {
            "id": "1001",
            "username": "coder",
            "email": "coder@example.com",
            "active": "true",
        }
        r.hset(key, mapping=data)

        # HGETALL returns dict when decode_responses=True
        profile = r.hgetall(key)
        assert profile == data

    def test_hgetall_empty_when_missing(self, r):
        assert r.hgetall("integration:hash:nonexistent") == {}


class TestEndToEndScenarioIntegration:
    """Full lifecycle scenario combining all features."""

    def test_ecommerce_cart_lifecycle(self, r):
        cart_key = "integration:cart:session_123"
        lock_key = "integration:cart:lock"
        items_list = "integration:cart:items"

        # Cleanup
        r.delete(cart_key, lock_key, items_list)

        # 1. Acquire mutex lock with NX and EX (10s expiry)
        acquired = r.set(lock_key, "worker_1", nx=True, ex=10)
        assert acquired is True

        # Second worker cannot acquire
        assert r.set(lock_key, "worker_2", nx=True, ex=10) is None

        # 2. Store session cart metadata in hash
        r.hset(cart_key, mapping={"user_id": "42", "currency": "USD", "status": "active"})
        cart_meta = r.hgetall(cart_key)
        assert cart_meta["user_id"] == "42"

        # 3. Add items to cart list
        r.lpush(items_list, "item_sku_101", "item_sku_102")
        items = r.lrange(items_list, 0, -1)
        assert len(items) == 2

        # 4. Release lock with DEL and clean up
        assert r.delete(lock_key) == 1
        assert r.get(lock_key) is None

        # 5. Delete all created keys
        assert r.delete(cart_key, items_list) == 2
        assert r.hgetall(cart_key) == {}
        assert r.lrange(items_list, 0, -1) == []
