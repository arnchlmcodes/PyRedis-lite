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
