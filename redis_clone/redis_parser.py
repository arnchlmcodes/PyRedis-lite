from enum import Enum


class Protocol_2_Data_Types(Enum):

    SIMPLE_STRING = "+"
    ERROR = "-"
    INTEGER = ":"
    BULK_STRING = "$"
    ARRAY = "*"


class Parser:
    
  
    def parse(self, data: bytes) -> tuple[str, list[str]]:
        
        text = data.decode("utf-8")
        return self._parse_text(text)


    def _parse_text(self, text: str) -> tuple[str, list[str]]:
        if not text:
            raise ValueError("Empty RESP2 message")

        prefix = text[0]

        if prefix == Protocol_2_Data_Types.ARRAY.value:
            return self._parse_array(text)

        raise ValueError(
            f"Unsupported top-level RESP2 type: {prefix!r}. "
            "Client commands must be sent as RESP arrays (*...)."
        )

    def _parse_array(self, text: str) -> tuple[str, list[str]]:
        
        lines = text.split("\r\n")
        count = int(lines[0][1:])  

        elements: list[str] = []
        index = 1 
        for _ in range(count):
            if index >= len(lines):
                raise ValueError("Truncated RESP2 array: missing bulk-string header")

            header = lines[index]
            if not header.startswith(Protocol_2_Data_Types.BULK_STRING.value):
                raise ValueError(
                    f"Expected bulk-string header ('$'), got {header!r}"
                )

            index += 1
            if index >= len(lines):
                raise ValueError("Truncated RESP2 array: missing bulk-string body")

            elements.append(lines[index])
            index += 1 

        if not elements:
            raise ValueError("RESP2 array contained zero elements (no command)")

        command_name = elements[0].upper()
        args = elements[1:]
        return command_name, args
