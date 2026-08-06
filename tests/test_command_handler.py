"""Unit tests for CommandHandler (no networking, no sockets)."""
import pytest
from redis_clone.command_handler import CommandHandler
from redis_clone.database import Database
from redis_clone.response_builder import ResponseBuilder

CRLF = b"\r\n"


@pytest.fixture()
def handler():
    db = Database()
    response = ResponseBuilder()
    return CommandHandler(db, response)


@pytest.fixture()
def handler_with_db():
    """Return both handler and its backing db so tests can inspect state."""
    db = Database()
    response = ResponseBuilder()
    return CommandHandler(db, response), db


class TestPing:
    def test_ping_no_args(self, handler):
        assert handler.handle("PING", []) == b"+PONG\r\n"

    def test_ping_with_message(self, handler):
        result = handler.handle("PING", ["hello"])
        assert result == b"$5\r\nhello\r\n"


class TestEcho:
    def test_echo_returns_bulk_string(self, handler):
        result = handler.handle("ECHO", ["hello world"])
        assert result == b"$11\r\nhello world\r\n"

    def test_echo_no_args_returns_error(self, handler):
        result = handler.handle("ECHO", [])
        assert result.startswith(b"-ERR")
        assert b"echo" in result.lower()


class TestSet:
    def test_set_returns_ok(self, handler_with_db):
        handler, db = handler_with_db
        result = handler.handle("SET", ["mykey", "myval"])
        assert result == b"+OK\r\n"

    def test_set_persists_in_db(self, handler_with_db):
        handler, db = handler_with_db
        handler.handle("SET", ["mykey", "myval"])
        assert db.get("mykey") == "myval"

    def test_set_too_few_args_returns_error(self, handler):
        result = handler.handle("SET", ["onlykey"])
        assert result.startswith(b"-ERR")
        assert b"set" in result.lower()

    def test_set_no_args_returns_error(self, handler):
        result = handler.handle("SET", [])
        assert result.startswith(b"-ERR")


class TestGet:
    def test_get_existing_key(self, handler_with_db):
        handler, db = handler_with_db
        db.set("foo", "bar")
        result = handler.handle("GET", ["foo"])
        assert result == b"$3\r\nbar\r\n"

    def test_get_missing_key_returns_null_bulk_string(self, handler):
        result = handler.handle("GET", ["no_such_key"])
        assert result == b"$-1\r\n"

    def test_get_no_args_returns_error(self, handler):
        result = handler.handle("GET", [])
        assert result.startswith(b"-ERR")
        assert b"get" in result.lower()


class TestUnknownCommand:
    def test_unknown_command_returns_error(self, handler):
        result = handler.handle("FOOBAR", [])
        assert result.startswith(b"-ERR")
        assert b"foobar" in result.lower()


class TestSetThenGet:
    def test_set_then_get_roundtrip(self, handler):
        handler.handle("SET", ["name", "alice"])
        result = handler.handle("GET", ["name"])
        assert result == b"$5\r\nalice\r\n"

    def test_overwrite_then_get(self, handler):
        handler.handle("SET", ["k", "v1"])
        handler.handle("SET", ["k", "v2"])
        result = handler.handle("GET", ["k"])
        assert result == b"$2\r\nv2\r\n"
