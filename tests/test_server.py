import threading
import time
import pytest
import redis

from redis_clone.server import Server

TEST_HOST = "127.0.0.1"
TEST_PORT = 6380


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
