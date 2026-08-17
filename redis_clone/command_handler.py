"""
Command router.

Receives a parsed (command, args) pair and produces a RESP-encoded
bytes response. Knows nothing about sockets or byte parsing.
"""
from __future__ import annotations

import logging

from redis_clone.database import Database
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

        Supported commands: PING, ECHO, SET, GET, DEL.
        Unknown commands produce an ERR error response.
        """
        logger.debug("Command=%r args=%r", command, args)

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

        return self._response.error(f"unknown command '{command}'", kind="ERR")

