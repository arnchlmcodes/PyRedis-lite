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
    server = Server(host=TEST_HOST, port=TEST_PORT)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield server
    server.stop()
    thread.join(timeout=2)


@pytest.fixture
def client(redis_server):
    c = redis.Redis(host=TEST_HOST, port=TEST_PORT, decode_responses=True)
    yield c
    c.close()


def test_ping(client):
    assert client.ping() is True


def test_echo(client):
    assert client.echo("hello") == "hello"


def test_set_get(client):
    assert client.set("name", "alice") is True
    assert client.get("name") == "alice"


def test_nonexistent_get(client):
    assert client.get("does_not_exist") is None


def test_concurrent_clients(redis_server):
    """Multiple simultaneous connections must each get correct responses."""
    num_clients = 5
    errors: list[Exception] = []

    def client_work(n: int) -> None:
        c = redis.Redis(host=TEST_HOST, port=TEST_PORT, decode_responses=True)
        try:
            key = f"concurrent-key-{n}"
            value = f"value-{n}"
            assert c.set(key, value) is True
            assert c.get(key) == value
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            c.close()

    threads = [
        threading.Thread(target=client_work, args=(i,))
        for i in range(num_clients)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"Errors in concurrent clients: {errors}"


def test_server_set_options(client):
    # NX
    assert client.set("k_nx", "v1", nx=True) is True
    assert client.set("k_nx", "v2", nx=True) is None

    # XX
    assert client.set("k_xx_missing", "v1", xx=True) is None
    client.set("k_xx", "v1")
    assert client.set("k_xx", "v2", xx=True) is True
    assert client.get("k_xx") == "v2"

    # GET
    assert client.set("k_get", "v_new", get=True) is None
    client.set("k_get_prev", "old_val")
    assert client.set("k_get_prev", "new_val", get=True) == "old_val"
    assert client.get("k_get_prev") == "new_val"


def test_server_del(client):
    client.set("d1", "1")
    client.set("d2", "2")
    assert client.delete("d1", "d2", "d3") == 2
    assert client.get("d1") is None
    assert client.get("d2") is None


def test_server_lists(client):
    # LPUSH / RPUSH / LLEN / LRANGE
    assert client.lpush("server_list", "world") == 1
    assert client.lpush("server_list", "hello") == 2
    assert client.rpush("server_list", "foo", "bar") == 4
    assert client.llen("server_list") == 4
    assert client.lrange("server_list", 0, -1) == ["hello", "world", "foo", "bar"]
    assert client.lrange("server_list", -2, -1) == ["foo", "bar"]

    # LPOP / RPOP
    assert client.lpop("server_list") == "hello"
    assert client.rpop("server_list") == "bar"
    assert client.lpop("server_list", count=2) == ["world", "foo"]
    assert client.lpop("server_list") is None


def test_server_wrongtype(client):
    client.set("str_key", "string_val")
    with pytest.raises(redis.exceptions.ResponseError, match="WRONGTYPE"):
        client.lpush("str_key", "item")

    client.rpush("list_key", "item")
    with pytest.raises(redis.exceptions.ResponseError, match="WRONGTYPE"):
        client.set("list_key", "new_val")


