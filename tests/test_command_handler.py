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


class TestSetOptions:
    def test_set_nx_on_missing_key_returns_ok(self, handler_with_db):
        handler, db = handler_with_db
        result = handler.handle("SET", ["k", "v", "NX"])
        assert result == b"+OK\r\n"
        assert db.get("k") == "v"

    def test_set_nx_on_existing_key_returns_nil(self, handler_with_db):
        handler, db = handler_with_db
        handler.handle("SET", ["k", "v1"])
        result = handler.handle("SET", ["k", "v2", "NX"])
        assert result == b"$-1\r\n"
        assert db.get("k") == "v1"

    def test_set_xx_on_missing_key_returns_nil(self, handler_with_db):
        handler, db = handler_with_db
        result = handler.handle("SET", ["k", "v", "XX"])
        assert result == b"$-1\r\n"
        assert db.get("k") is None

    def test_set_xx_on_existing_key_returns_ok(self, handler_with_db):
        handler, db = handler_with_db
        handler.handle("SET", ["k", "v1"])
        result = handler.handle("SET", ["k", "v2", "XX"])
        assert result == b"+OK\r\n"
        assert db.get("k") == "v2"

    def test_set_get_flag_returns_old_value(self, handler_with_db):
        handler, db = handler_with_db
        handler.handle("SET", ["k", "old"])
        result = handler.handle("SET", ["k", "new", "GET"])
        assert result == b"$3\r\nold\r\n"
        assert db.get("k") == "new"

    def test_set_get_flag_on_missing_key_returns_nil(self, handler_with_db):
        handler, db = handler_with_db
        result = handler.handle("SET", ["k", "new", "GET"])
        assert result == b"$-1\r\n"
        assert db.get("k") == "new"

    def test_set_nx_get_when_exists(self, handler_with_db):
        handler, db = handler_with_db
        handler.handle("SET", ["k", "old"])
        result = handler.handle("SET", ["k", "new", "NX", "GET"])
        assert result == b"$3\r\nold\r\n"
        assert db.get("k") == "old"

    def test_set_xx_get_when_missing(self, handler_with_db):
        handler, db = handler_with_db
        result = handler.handle("SET", ["k", "new", "XX", "GET"])
        assert result == b"$-1\r\n"
        assert db.get("k") is None

    def test_set_nx_ex_composition(self, handler_with_db):
        handler, db = handler_with_db
        result = handler.handle("SET", ["k", "v", "NX", "EX", "10"])
        assert result == b"+OK\r\n"
        assert db.get("k") == "v"

    def test_set_invalid_option_syntax_error(self, handler):
        result = handler.handle("SET", ["k", "v", "INVALID"])
        assert result.startswith(b"-ERR")
        assert b"syntax error" in result.lower()

    def test_set_ex_missing_value_syntax_error(self, handler):
        result = handler.handle("SET", ["k", "v", "EX"])
        assert result.startswith(b"-ERR")
        assert b"syntax error" in result.lower()

    def test_set_ex_non_integer_value_error(self, handler):
        result = handler.handle("SET", ["k", "v", "EX", "not_a_number"])
        assert result.startswith(b"-ERR")
        assert b"not an integer" in result.lower()


class TestDel:
    def test_del_no_args_returns_error(self, handler):
        result = handler.handle("DEL", [])
        assert result.startswith(b"-ERR")
        assert b"del" in result.lower()

    def test_del_single_existing_key(self, handler_with_db):
        handler, db = handler_with_db
        handler.handle("SET", ["k", "v"])
        result = handler.handle("DEL", ["k"])
        assert result == b":1\r\n"
        assert db.get("k") is None

    def test_del_nonexistent_key(self, handler):
        result = handler.handle("DEL", ["nonexistent"])
        assert result == b":0\r\n"

    def test_del_multiple_keys(self, handler_with_db):
        handler, db = handler_with_db
        handler.handle("SET", ["k1", "v1"])
        handler.handle("SET", ["k2", "v2"])
        handler.handle("SET", ["k3", "v3"])
        result = handler.handle("DEL", ["k1", "k2", "k4"])
        assert result == b":2\r\n"
        assert db.get("k1") is None
        assert db.get("k2") is None
        assert db.get("k3") == "v3"

