import os
import socket
import logging

from redis_clone.redis_parser import Parser
from redis_clone.response_builder import ResponseBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pyredis-lite")


DEFAULT_HOST = os.environ.get("REDIS_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("REDIS_PORT", 6379))
BUFFER_SIZE = 1024


class Server:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._parser = Parser()
        self._response = ResponseBuilder()
        self._server_socket: socket.socket = self._create_socket()
        self.data_store: dict[str, str] = {}
        self.running: bool = False

    def _create_socket(self) -> socket.socket:
       
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        logger.debug("Server socket created.")
        return sock

    def _bind_socket(self) -> None:
        self._server_socket.bind((self.host, self.port))
        logger.info("Socket bound to %s:%d", self.host, self.port)

    def _listen(self, backlog: int = 5) -> None:
   
        self._server_socket.listen(backlog)
        logger.info("Listening … (backlog=%d)", backlog)

    def _accept_connections(self) -> None:
        logger.info("Ready to accept connections on %s:%d", self.host, self.port)
        while self.running:
            try:
                client_socket, client_address = self._server_socket.accept()
            except OSError:
                break
            logger.info("New connection from %s:%d", *client_address)
            self._handle_connection(client_socket, client_address)

    def stop(self) -> None:
        self.running = False
        try:
            self._server_socket.close()
        except OSError:
            pass


    def run(self) -> None:
        self.running = True
        try:
            self._bind_socket()
            self._listen()
            self._accept_connections()
        finally:
            self.running = False
            logger.info("Server socket closed.")


    def _handle_connection(
        self,
        client_socket: socket.socket,
        client_address: tuple[str, int],
    ) -> None:

        with client_socket:
            while True:
                try:
                    data = client_socket.recv(BUFFER_SIZE)
                except ConnectionResetError:
                    logger.warning(
                        "Connection reset by %s:%d", *client_address
                    )
                    break

                if not data:
                    logger.info(
                        "Connection closed by %s:%d", *client_address
                    )
                    break

                logger.debug("Received %d bytes from %s:%d", len(data), *client_address)

                response = self._process_command(data)
                client_socket.sendall(response)

    def _process_command(self, data: bytes) -> bytes:

        try:
            command, args = self._parser.parse(data)
        except Exception as exc:  # noqa: BLE001
            logger.error("Parse error: %s", exc)
            return self._response.error(f"Parse error: {exc}", kind="ERR")

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
                return self._response.error("wrong number of arguments for 'set' command", kind="ERR")
            self.data_store[args[0]] = args[1]
            return self._response.simple_string("OK")

        if command == "GET":
            if not args:
                return self._response.error("wrong number of arguments for 'get' command", kind="ERR")
            value = self.data_store.get(args[0])
            return self._response._build_protocol_2_bulk_string(value)

        return self._response.error(
            f"unknown command '{command}'", kind="ERR"
        )


if __name__ == "__main__":
    server = Server()
    server.run()
