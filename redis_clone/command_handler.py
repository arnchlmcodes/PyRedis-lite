"""
Command router.

Receives a parsed (command, args) pair and produces a RESP-encoded
bytes response. Knows nothing about sockets or byte parsing.
"""
from __future__ import annotations

import logging

from redis_clone.database import Database, WrongTypeError
from redis_clone.response_builder import ResponseBuilder

logger = logging.getLogger("pyredis-lite.command_handler")


class CommandHandler:
    """Route Redis commands to the appropriate database operations."""

    def __init__(self, db: Database, response: ResponseBuilder) -> None:
        self._db = db
        self._response = response

    def handle(self, command: str, args: list[str]) -> bytes:
        """
        Dispatch *command* with *args* and return a RESP-encoded response.

        Supported commands: PING, ECHO, SET, GET, DEL, LPUSH, RPUSH, LRANGE, LLEN, LPOP, RPOP, HSET, HGET, HGETALL, HDEL, HEXISTS, HLEN.
        Unknown commands produce an ERR error response.
        """
        logger.debug("Command=%r args=%r", command, args)

        try:
            return self._dispatch(command, args)
        except WrongTypeError:
            return self._response.wrong_type()

    def _dispatch(self, command: str, args: list[str]) -> bytes:
        if command == "PING":
            if args:
                return self._response.bulk_string(args[0])
            return self._response.simple_string("PONG")

        if command == "ECHO":
            if not args:
                return self._response.error(
                    "wrong number of arguments for 'echo' command", kind="ERR"
                )
            return self._response.bulk_string(args[0])

        if command == "SET":
            if len(args) < 2:
                return self._response.error(
                    "wrong number of arguments for 'set' command", kind="ERR"
                )
            key, value = args[0], args[1]
            options = args[2:]
            kwargs: dict[str, int | bool] = {}
            i = 0
            while i < len(options):
                opt = options[i].upper()
                if opt in ("EX", "PX", "EXAT", "PXAT"):
                    if i + 1 >= len(options):
                        return self._response.error(
                            "syntax error", kind="ERR"
                        )
                    try:
                        kwargs[opt.lower()] = int(options[i + 1])
                    except ValueError:
                        return self._response.error(
                            "value is not an integer or out of range",
                            kind="ERR",
                        )
                    i += 2
                elif opt == "KEEPTTL":
                    kwargs["keepttl"] = True
                    i += 1
                elif opt == "NX":
                    kwargs["nx"] = True
                    i += 1
                elif opt == "XX":
                    kwargs["xx"] = True
                    i += 1
                elif opt == "GET":
                    kwargs["get"] = True
                    i += 1
                else:
                    return self._response.error(
                        "syntax error", kind="ERR"
                    )

            result = self._db.set(key, value, **kwargs)

            use_get = kwargs.get("get", False)
            if use_get:
                # GET flag: always return the old value (str or None).
                return self._response.bulk_string(result)  # type: ignore[arg-type]
            # Without GET: _NOT_SET means NX/XX rejected the write.
            if result is Database._NOT_SET:
                return self._response.bulk_string(None)
            return self._response.simple_string("OK")

        if command == "GET":
            if not args:
                return self._response.error(
                    "wrong number of arguments for 'get' command", kind="ERR"
                )
            value = self._db.get(args[0])
            return self._response.bulk_string(value)

        if command == "DEL":
            if not args:
                return self._response.error(
                    "wrong number of arguments for 'del' command", kind="ERR"
                )
            count = self._db.delete(*args)
            return self._response.integer(count)

        if command == "LPUSH":
            if len(args) < 2:
                return self._response.error(
                    "wrong number of arguments for 'lpush' command", kind="ERR"
                )
            count = self._db.lpush(args[0], *args[1:])
            return self._response.integer(count)

        if command == "RPUSH":
            if len(args) < 2:
                return self._response.error(
                    "wrong number of arguments for 'rpush' command", kind="ERR"
                )
            count = self._db.rpush(args[0], *args[1:])
            return self._response.integer(count)

        if command == "LRANGE":
            if len(args) != 3:
                return self._response.error(
                    "wrong number of arguments for 'lrange' command", kind="ERR"
                )
            try:
                start = int(args[1])
                stop = int(args[2])
            except ValueError:
                return self._response.error(
                    "value is not an integer or out of range", kind="ERR"
                )
            items = self._db.lrange(args[0], start, stop)
            return self._response.array(
                [self._response.bulk_string(item) for item in items]
            )

        if command == "LLEN":
            if len(args) != 1:
                return self._response.error(
                    "wrong number of arguments for 'llen' command", kind="ERR"
                )
            length = self._db.llen(args[0])
            return self._response.integer(length)

        if command == "LPOP":
            if len(args) < 1 or len(args) > 2:
                return self._response.error(
                    "wrong number of arguments for 'lpop' command", kind="ERR"
                )
            if len(args) == 1:
                val = self._db.lpop(args[0])
                return self._response.bulk_string(val)  # type: ignore[arg-type]
            try:
                count = int(args[1])
            except ValueError:
                return self._response.error(
                    "value is not an integer or out of range", kind="ERR"
                )
            if count < 0:
                return self._response.error(
                    "value is out of range, must be positive", kind="ERR"
                )
            vals = self._db.lpop(args[0], count=count)
            if vals is None:
                return self._response.null_bulk_string()
            return self._response.array(
                [self._response.bulk_string(item) for item in vals]  # type: ignore[union-attr]
            )

        if command == "RPOP":
            if len(args) < 1 or len(args) > 2:
                return self._response.error(
                    "wrong number of arguments for 'rpop' command", kind="ERR"
                )
            if len(args) == 1:
                val = self._db.rpop(args[0])
                return self._response.bulk_string(val)  # type: ignore[arg-type]
            try:
                count = int(args[1])
            except ValueError:
                return self._response.error(
                    "value is not an integer or out of range", kind="ERR"
                )
            if count < 0:
                return self._response.error(
                    "value is out of range, must be positive", kind="ERR"
                )
            vals = self._db.rpop(args[0], count=count)
            if vals is None:
                return self._response.null_bulk_string()
            return self._response.array(
                [self._response.bulk_string(item) for item in vals]  # type: ignore[union-attr]
            )

        if command == "HSET":
            if len(args) < 3 or (len(args) - 1) % 2 != 0:
                return self._response.error(
                    "wrong number of arguments for 'hset' command", kind="ERR"
                )
            count = self._db.hset(args[0], *args[1:])
            return self._response.integer(count)

        if command == "HGET":
            if len(args) != 2:
                return self._response.error(
                    "wrong number of arguments for 'hget' command", kind="ERR"
                )
            val = self._db.hget(args[0], args[1])
            return self._response.bulk_string(val)

        if command == "HGETALL":
            if len(args) != 1:
                return self._response.error(
                    "wrong number of arguments for 'hgetall' command", kind="ERR"
                )
            items = self._db.hgetall(args[0])
            return self._response.array(
                [self._response.bulk_string(item) for item in items]
            )

        if command == "HDEL":
            if len(args) < 2:
                return self._response.error(
                    "wrong number of arguments for 'hdel' command", kind="ERR"
                )
            count = self._db.hdel(args[0], *args[1:])
            return self._response.integer(count)

        if command == "HEXISTS":
            if len(args) != 2:
                return self._response.error(
                    "wrong number of arguments for 'hexists' command", kind="ERR"
                )
            exists = self._db.hexists(args[0], args[1])
            return self._response.integer(1 if exists else 0)

        if command == "HLEN":
            if len(args) != 1:
                return self._response.error(
                    "wrong number of arguments for 'hlen' command", kind="ERR"
                )
            length = self._db.hlen(args[0])
            return self._response.integer(length)

        return self._response.error(f"unknown command '{command}'", kind="ERR")

