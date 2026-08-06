import asyncio
import logging
import os

from redis_clone.command_handler import CommandHandler
from redis_clone.database import Database
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
    """Asyncio TCP server speaking RESP2."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._parser = Parser()
        self._response = ResponseBuilder()
        self._db = Database()
        self._handler = CommandHandler(self._db, self._response)
        # Set by _serve(); used by stop() for cross-thread shutdown.
        self._asyncio_server: asyncio.Server | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Public interface (unchanged from the blocking implementation)
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the event loop and block until stop() is called."""
        try:
            asyncio.run(self._serve())
        except asyncio.CancelledError:
            pass  # Normal shutdown path: stop() cancelled serve_forever()

    def stop(self) -> None:
        """
        Signal the server to shut down.

        Safe to call from any thread (e.g. test teardown running in the
        main thread while the event loop lives in a daemon thread).
        """
        if self._asyncio_server is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._asyncio_server.close)

    # ------------------------------------------------------------------
    # Internal asyncio machinery
    # ------------------------------------------------------------------

    async def _serve(self) -> None:
        """Bind, listen, and serve connections until the server is closed."""
        self._loop = asyncio.get_running_loop()
        self._asyncio_server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            reuse_address=True,
        )
        addrs = ", ".join(
            str(sock.getsockname()) for sock in self._asyncio_server.sockets
        )
        logger.info("Listening on %s", addrs)

        async with self._asyncio_server:
            await self._asyncio_server.serve_forever()

        logger.info("Server stopped.")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Coroutine spawned for every accepted connection."""
        addr = writer.get_extra_info("peername")
        logger.info("New connection from %s:%d", *addr)

        try:
            while True:
                try:
                    data = await reader.read(BUFFER_SIZE)
                except ConnectionResetError:
                    logger.warning("Connection reset by %s:%d", *addr)
                    break

                if not data:
                    logger.info("Connection closed by %s:%d", *addr)
                    break

                logger.debug("Received %d bytes from %s:%d", len(data), *addr)
                response = self._process_command(data)
                writer.write(response)
                await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    def _process_command(self, data: bytes) -> bytes:
        """Parse raw bytes and delegate to the command handler."""
        try:
            command, args = self._parser.parse(data)
        except Exception as exc:  # noqa: BLE001
            logger.error("Parse error: %s", exc)
            return self._response.error(f"Parse error: {exc}", kind="ERR")

        return self._handler.handle(command, args)


def main() -> None:
    """Entry point for the ``pyredis-lite`` console script."""
    server = Server()
    server.run()


if __name__ == "__main__":
    main()
