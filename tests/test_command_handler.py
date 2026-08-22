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


class TestListCommands:
    def test_lpush_and_rpush_and_llen(self, handler):
        assert handler.handle("LPUSH", ["mylist", "world"]) == b":1\r\n"
        assert handler.handle("LPUSH", ["mylist", "hello"]) == b":2\r\n"
        assert handler.handle("RPUSH", ["mylist", "foo", "bar"]) == b":4\r\n"
        assert handler.handle("LLEN", ["mylist"]) == b":4\r\n"

    def test_lrange(self, handler):
        handler.handle("RPUSH", ["mylist", "a", "b", "c"])
        res = handler.handle("LRANGE", ["mylist", "0", "-1"])
        assert res == b"*3\r\n$1\r\na\r\n$1\r\nb\r\n$1\r\nc\r\n"

    def test_lpop_and_rpop(self, handler):
        handler.handle("RPUSH", ["mylist", "a", "b", "c", "d"])
        assert handler.handle("LPOP", ["mylist"]) == b"$1\r\na\r\n"
        assert handler.handle("RPOP", ["mylist"]) == b"$1\r\nd\r\n"
        assert handler.handle("LPOP", ["mylist", "2"]) == b"*2\r\n$1\r\nb\r\n$1\r\nc\r\n"
        assert handler.handle("LPOP", ["mylist"]) == b"$-1\r\n"


class TestWrongTypeHandling:
    def test_wrongtype_get_on_list(self, handler):
        handler.handle("RPUSH", ["mylist", "a"])
        res = handler.handle("GET", ["mylist"])
        assert res.startswith(b"-WRONGTYPE")

    def test_wrongtype_list_ops_on_string(self, handler):
        handler.handle("SET", ["mystr", "hello"])
        assert handler.handle("LPUSH", ["mystr", "a"]).startswith(b"-WRONGTYPE")
        assert handler.handle("RPUSH", ["mystr", "a"]).startswith(b"-WRONGTYPE")
        assert handler.handle("LRANGE", ["mystr", "0", "-1"]).startswith(b"-WRONGTYPE")
        assert handler.handle("LLEN", ["mystr"]).startswith(b"-WRONGTYPE")
        assert handler.handle("LPOP", ["mystr"]).startswith(b"-WRONGTYPE")
        assert handler.handle("RPOP", ["mystr"]).startswith(b"-WRONGTYPE")

    def test_wrongtype_hash_ops_on_string_and_list(self, handler):
        handler.handle("SET", ["mystr", "hello"])
        assert handler.handle("HSET", ["mystr", "f", "v"]).startswith(b"-WRONGTYPE")
        assert handler.handle("HGET", ["mystr", "f"]).startswith(b"-WRONGTYPE")
        assert handler.handle("HGETALL", ["mystr"]).startswith(b"-WRONGTYPE")
        assert handler.handle("HDEL", ["mystr", "f"]).startswith(b"-WRONGTYPE")
        assert handler.handle("HEXISTS", ["mystr", "f"]).startswith(b"-WRONGTYPE")
        assert handler.handle("HLEN", ["mystr"]).startswith(b"-WRONGTYPE")

        handler.handle("RPUSH", ["mylist", "item"])
        assert handler.handle("HSET", ["mylist", "f", "v"]).startswith(b"-WRONGTYPE")
        assert handler.handle("HGET", ["mylist", "f"]).startswith(b"-WRONGTYPE")
        assert handler.handle("HGETALL", ["mylist"]).startswith(b"-WRONGTYPE")


class TestHashCommands:
    def test_hset_single_and_multi_field(self, handler):
        assert handler.handle("HSET", ["myhash", "f1", "v1"]) == b":1\r\n"
        assert handler.handle("HSET", ["myhash", "f1", "v1"]) == b":0\r\n"
        assert handler.handle("HSET", ["myhash", "f2", "v2", "f3", "v3"]) == b":2\r\n"

    def test_hset_syntax_errors(self, handler):
        assert handler.handle("HSET", []).startswith(b"-ERR")
        assert handler.handle("HSET", ["myhash"]).startswith(b"-ERR")
        assert handler.handle("HSET", ["myhash", "f1"]).startswith(b"-ERR")
        assert handler.handle("HSET", ["myhash", "f1", "v1", "f2"]).startswith(b"-ERR")

    def test_hget(self, handler):
        handler.handle("HSET", ["myhash", "f1", "hello"])
        assert handler.handle("HGET", ["myhash", "f1"]) == b"$5\r\nhello\r\n"
        assert handler.handle("HGET", ["myhash", "f2"]) == b"$-1\r\n"
        assert handler.handle("HGET", ["missing", "f1"]) == b"$-1\r\n"

    def test_hgetall(self, handler):
        assert handler.handle("HGETALL", ["missing"]) == b"*0\r\n"
        handler.handle("HSET", ["user", "name", "alice", "age", "25"])
        res = handler.handle("HGETALL", ["user"])
        assert res == b"*4\r\n$4\r\nname\r\n$5\r\nalice\r\n$3\r\nage\r\n$2\r\n25\r\n"

    def test_hdel(self, handler):
        handler.handle("HSET", ["myhash", "f1", "v1", "f2", "v2"])
        assert handler.handle("HDEL", ["myhash", "f1", "f3"]) == b":1\r\n"
        assert handler.handle("HGET", ["myhash", "f1"]) == b"$-1\r\n"
        assert handler.handle("HDEL", ["myhash", "f2"]) == b":1\r\n"
        # Deleting all fields cleans up the hash
        assert handler.handle("HDEL", ["myhash", "f2"]) == b":0\r\n"

    def test_hexists(self, handler):
        handler.handle("HSET", ["myhash", "f1", "v1"])
        assert handler.handle("HEXISTS", ["myhash", "f1"]) == b":1\r\n"
        assert handler.handle("HEXISTS", ["myhash", "f2"]) == b":0\r\n"
        assert handler.handle("HEXISTS", ["missing", "f1"]) == b":0\r\n"

    def test_hlen(self, handler):
        assert handler.handle("HLEN", ["missing"]) == b":0\r\n"
        handler.handle("HSET", ["myhash", "f1", "v1", "f2", "v2"])
        assert handler.handle("HLEN", ["myhash"]) == b":2\r\n"

    def test_hash_syntax_errors(self, handler):
        assert handler.handle("HGET", ["k"]).startswith(b"-ERR")
        assert handler.handle("HGETALL", []).startswith(b"-ERR")
        assert handler.handle("HGETALL", ["k", "extra"]).startswith(b"-ERR")
        assert handler.handle("HDEL", ["k"]).startswith(b"-ERR")
        assert handler.handle("HEXISTS", ["k"]).startswith(b"-ERR")
        assert handler.handle("HLEN", []).startswith(b"-ERR")



