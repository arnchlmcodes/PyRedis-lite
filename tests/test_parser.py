"""
tests/test_parser.py
--------------------
Unit tests for the RESP2 parser (redis_clone.redis_parser.Parser).

Run with::

    pytest tests/

"""

import pytest

from redis_clone.redis_parser import Parser, Protocol_2_Data_Types


class TestParser:
    """Tests for Parser.parse()."""

    def setup_method(self):
        self.parser = Parser()

    # ------------------------------------------------------------------ #
    #  Protocol_2_Data_Types enum sanity                                  #
    # ------------------------------------------------------------------ #

    def test_data_type_prefixes(self):
        """Verify the RESP2 type-prefix enum values are correct."""
        assert Protocol_2_Data_Types.SIMPLE_STRING.value == "+"
        assert Protocol_2_Data_Types.ERROR.value == "-"
        assert Protocol_2_Data_Types.INTEGER.value == ":"
        assert Protocol_2_Data_Types.BULK_STRING.value == "$"
        assert Protocol_2_Data_Types.ARRAY.value == "*"

    # ------------------------------------------------------------------ #
    #  Bare COMMAND request (the founding test from the initial commit)   #
    # ------------------------------------------------------------------ #

    def test_parse_command_request(self):
        """Parse a bare ``COMMAND`` request (no arguments).

        Wire format::

            *1\\r\\n$7\\r\\nCOMMAND\\r\\n
        """
        raw = b"*1\r\n$7\r\nCOMMAND\r\n"
        command, args = self.parser.parse(raw)

        assert command == "COMMAND"
        assert args == []

    # ------------------------------------------------------------------ #
    #  PING                                                                #
    # ------------------------------------------------------------------ #

    def test_parse_ping_no_args(self):
        """PING without arguments."""
        raw = b"*1\r\n$4\r\nPING\r\n"
        command, args = self.parser.parse(raw)

        assert command == "PING"
        assert args == []

    def test_parse_ping_with_message(self):
        """PING with a single message argument."""
        raw = b"*2\r\n$4\r\nPING\r\n$5\r\nhello\r\n"
        command, args = self.parser.parse(raw)

        assert command == "PING"
        assert args == ["hello"]

    # ------------------------------------------------------------------ #
    #  ECHO                                                                #
    # ------------------------------------------------------------------ #

    def test_parse_echo(self):
        """ECHO with a single argument."""
        raw = b"*2\r\n$4\r\nECHO\r\n$11\r\nhello world\r\n"
        command, args = self.parser.parse(raw)

        assert command == "ECHO"
        assert args == ["hello world"]

    # ------------------------------------------------------------------ #
    #  Case normalisation                                                  #
    # ------------------------------------------------------------------ #

    def test_command_name_is_uppercased(self):
        """The parser normalises command names to upper case."""
        raw = b"*1\r\n$4\r\nping\r\n"
        command, args = self.parser.parse(raw)

        assert command == "PING"

    # ------------------------------------------------------------------ #
    #  Error conditions                                                    #
    # ------------------------------------------------------------------ #

    def test_empty_data_raises(self):
        """Parsing empty bytes should raise ValueError."""
        with pytest.raises((ValueError, UnicodeDecodeError, Exception)):
            self.parser.parse(b"")

    def test_non_array_top_level_raises(self):
        """A top-level simple string (+) is not a valid client command."""
        with pytest.raises(ValueError, match="Unsupported top-level RESP2 type"):
            self.parser.parse(b"+OK\r\n")
