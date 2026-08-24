"""RESP2 parser using byte-offset scanning.

Two sentinel exceptions are used so callers can distinguish the two failure modes:

* ``Incomplete``     – the buffer holds a *valid* but *partial* command; the
                       caller should wait for more bytes and retry.
* ``ProtocolError``  – the bytes are structurally broken and the connection
                       should be closed.

``Parser.parse_one(buf, offset)`` returns ``(command_name, args, new_offset)``
where *new_offset* is the byte position in *buf* immediately after the last byte
consumed by this command.  The caller can slice ``buf[:new_offset]`` away and
try again to drain pipelined commands.
"""

from __future__ import annotations

from enum import Enum


class Incomplete(Exception):
    """Raised when the buffer ends in the middle of a valid RESP2 message."""


class ProtocolError(Exception):
    """Raised when the buffer contains structurally invalid RESP2 data."""


class Protocol_2_Data_Types(Enum):
    """RESP2 type prefixes (kept for backward compatibility)."""

    SIMPLE_STRING = "+"
    ERROR = "-"
    INTEGER = ":"
    BULK_STRING = "$"
    ARRAY = "*"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CRLF = b"\r\n"


def _find_crlf(buf: bytes | bytearray, start: int) -> int:
    """Return the index of the *start* of the next CRLF at or after *start*.

    Raises ``Incomplete`` if no CRLF is present in the remaining buffer.
    """
    idx = buf.find(_CRLF, start)
    if idx == -1:
        raise Incomplete("CRLF not found – waiting for more data")
    return idx


def _read_line(buf: bytes | bytearray, offset: int) -> tuple[bytes, int]:
    """Read one CRLF-terminated line starting at *offset*.

    Returns ``(line_without_crlf, next_offset)``.
    """
    crlf_pos = _find_crlf(buf, offset)
    line = buf[offset:crlf_pos]
    return line, crlf_pos + 2  # skip past \r\n


def _read_bulk_string(buf: bytes | bytearray, offset: int) -> tuple[str, int]:
    """Parse a ``$<len>\\r\\n<data>\\r\\n`` bulk string starting at *offset*.

    *offset* must point at the ``$`` character.

    Returns ``(string_value, next_offset)``.
    """
    if offset >= len(buf):
        raise Incomplete("Expected '$' but buffer is empty")

    if buf[offset : offset + 1] != b"$":
        raise ProtocolError(
            f"Expected bulk-string header '$', got {buf[offset:offset+1]!r}"
        )

    header_line, offset = _read_line(buf, offset + 1)  # skip '$'
    try:
        length = int(header_line)
    except ValueError:
        raise ProtocolError(f"Invalid bulk-string length: {header_line!r}")

    if length == -1:
        # Null bulk string
        return "", offset

    if length < 0:
        raise ProtocolError(f"Negative bulk-string length: {length}")

    end = offset + length
    if end > len(buf):
        raise Incomplete(
            f"Bulk-string body incomplete: need {length} bytes, "
            f"have {len(buf) - offset}"
        )

    value = buf[offset:end]

    # Expect the trailing \r\n
    if len(buf) < end + 2:
        raise Incomplete("Missing trailing CRLF after bulk-string body")
    if buf[end : end + 2] != _CRLF:
        raise ProtocolError(
            f"Expected CRLF after bulk-string body, got {buf[end:end+2]!r}"
        )

    return value.decode("utf-8"), end + 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class Parser:
    """Stateless RESP2 parser that works on raw bytes with an explicit offset."""

    # ------------------------------------------------------------------
    # Legacy shim – kept so existing call-sites that call parser.parse(data)
    # without an offset still work.
    # ------------------------------------------------------------------

    def parse(self, data: bytes) -> tuple[str, list[str]]:
        """Parse *data* as a single, complete RESP2 command.

        Raises ``Incomplete`` or ``ProtocolError`` on failure.
        Returns ``(command_name, args)``.
        """
        command, args, _ = self.parse_one(data, 0)
        return command, args

    # ------------------------------------------------------------------
    # Primary streaming interface
    # ------------------------------------------------------------------

    def parse_one(
        self, buf: bytes | bytearray, offset: int
    ) -> tuple[str, list[str], int]:
        """Parse one RESP2 command from *buf* starting at *offset*.

        Returns ``(command_name, args, new_offset)`` where *new_offset* is the
        byte position immediately after the last byte consumed.

        Raises:
            ``Incomplete``     – valid partial message; retry after more data.
            ``ProtocolError``  – structurally broken message; close connection.
        """
        if offset >= len(buf):
            raise Incomplete("Buffer is empty")

        prefix = buf[offset : offset + 1]

        if prefix == b"*":
            return self._parse_array(buf, offset)

        raise ProtocolError(
            f"Unsupported top-level RESP2 type: {prefix!r}. "
            "Client commands must be sent as RESP arrays (*...)."
        )

    def _parse_array(
        self, buf: bytes | bytearray, offset: int
    ) -> tuple[str, list[str], int]:
        # skip '*'
        count_line, offset = _read_line(buf, offset + 1)
        try:
            count = int(count_line)
        except ValueError:
            raise ProtocolError(f"Invalid array length: {count_line!r}")

        if count < 0:
            raise ProtocolError(f"Negative array length: {count}")

        elements: list[str] = []
        for _ in range(count):
            value, offset = _read_bulk_string(buf, offset)
            elements.append(value)

        if not elements:
            raise ProtocolError("RESP2 array contained zero elements (no command)")

        command_name = elements[0].upper()
        args = elements[1:]
        return command_name, args, offset
