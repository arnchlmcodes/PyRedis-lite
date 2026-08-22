from __future__ import annotations

CRLF = "\r\n"


class ResponseBuilder:
   
    def simple_string(self, value: str) -> bytes:
        return f"+{value}{CRLF}".encode("utf-8")


    def error(self, message: str, kind: str = "ERR") -> bytes:
       
        return f"-{kind} {message}{CRLF}".encode("utf-8")

    def wrong_type(
        self,
        message: str = "Operation against a key holding the wrong kind of value",
    ) -> bytes:
        return self.error(message, kind="WRONGTYPE")



    def integer(self, value: int) -> bytes:

        return f":{value}{CRLF}".encode("utf-8")

  

    def bulk_string(self, value: str | None) -> bytes:

        if value is None:
            return self.null_bulk_string()
        payload = value.encode("utf-8")
        header = f"${len(payload)}{CRLF}".encode("utf-8")
        return header + payload + CRLF.encode("utf-8")

    def null_bulk_string(self) -> bytes:
        return f"$-1{CRLF}".encode("utf-8")

    def _build_protocol_2_bulk_string(self, value: str | None) -> bytes:
        if value is None:
            return f"$-1{CRLF}".encode("utf-8")
        payload = value.encode("utf-8")
        return f"${len(payload)}{CRLF}".encode("utf-8") + payload + CRLF.encode("utf-8")


 #

    def array(self, elements: list[bytes] | None) -> bytes:

        if elements is None:
            return f"*-1{CRLF}".encode("utf-8")
        header = f"*{len(elements)}{CRLF}".encode("utf-8")
        return header + b"".join(elements)
