import pytest
from redis_clone.redis_parser import Incomplete, Parser, Protocol_2_Data_Types, ProtocolError


class TestProtocol2DataTypes:
    def test_prefixes(self):
        assert Protocol_2_Data_Types.SIMPLE_STRING.value == "+"
        assert Protocol_2_Data_Types.ERROR.value == "-"
        assert Protocol_2_Data_Types.INTEGER.value == ":"
        assert Protocol_2_Data_Types.BULK_STRING.value == "$"
        assert Protocol_2_Data_Types.ARRAY.value == "*"


class TestParser:
    def setup_method(self):
        self.parser = Parser()

    def test_parse_ping_no_args(self):
        command, args = self.parser.parse(b"*1\r\n$4\r\nPING\r\n")
        assert command == "PING"
        assert args == []

    def test_parse_ping_with_message(self):
        command, args = self.parser.parse(b"*2\r\n$4\r\nPING\r\n$5\r\nhello\r\n")
        assert command == "PING"
        assert args == ["hello"]

    def test_parse_echo(self):
        command, args = self.parser.parse(b"*2\r\n$4\r\nECHO\r\n$11\r\nhello world\r\n")
        assert command == "ECHO"
        assert args == ["hello world"]

    def test_parse_set(self):
        command, args = self.parser.parse(b"*3\r\n$3\r\nSET\r\n$3\r\nfoo\r\n$3\r\nbar\r\n")
        assert command == "SET"
        assert args == ["foo", "bar"]

    def test_parse_get(self):
        command, args = self.parser.parse(b"*2\r\n$3\r\nGET\r\n$3\r\nfoo\r\n")
        assert command == "GET"
        assert args == ["foo"]

    def test_command_uppercased(self):
        command, _ = self.parser.parse(b"*1\r\n$4\r\nping\r\n")
        assert command == "PING"

    def test_empty_raises(self):
        with pytest.raises(Incomplete):
            self.parser.parse(b"")

    def test_non_array_raises(self):
        with pytest.raises(ProtocolError, match="Unsupported top-level RESP2 type"):
            self.parser.parse(b"+OK\r\n")
