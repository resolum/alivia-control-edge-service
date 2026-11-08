"""Servidor WebSocket: el edge es el servidor y el ESP32 el cliente (ver docs/protocolo-websocket.md)."""

import asyncio
import json
import logging
from collections.abc import Callable
from http import HTTPStatus

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from alivia_edge.config import VoiceConfig
from alivia_edge.interfaces import AudioOutput
from alivia_edge.session import Session
from alivia_edge.transport.protocol import Hello, HelloRejected, parse_hello

logger = logging.getLogger(__name__)

BYTES_PER_SAMPLE = 2


class WebSocketOutput:
    def __init__(self, connection: ServerConnection):
        self._connection = connection

    async def send_json(self, message: dict) -> None:
        await self._connection.send(json.dumps(message))

    async def send_bytes(self, data: bytes) -> None:
        await self._connection.send(data)


class VoiceServer:
    def __init__(
        self,
        config: VoiceConfig,
        session_factory: Callable[[Hello, AudioOutput], Session],
    ):
        self._config = config
        self._factory = session_factory
        self._sessions: dict[str, tuple[Session, ServerConnection]] = {}

    def snapshot(self) -> list[dict]:
        return [session.snapshot() for session, _ in self._sessions.values()]

    async def run(self) -> None:
        cfg = self._config
        async with serve(
            self._handle,
            cfg.ws_host,
            cfg.ws_port,
            process_request=self._check_path,
            ping_interval=cfg.ping_interval_s,
            ping_timeout=cfg.ping_timeout_s,
            max_size=64 * 1024,
        ) as server:
            logger.info(
                "WebSocket escuchando en ws://%s:%s%s",
                cfg.ws_host,
                cfg.ws_port,
                cfg.ws_path,
            )
            await server.serve_forever()

    def _check_path(self, connection: ServerConnection, request):
        if request.path != self._config.ws_path:
            return connection.respond(HTTPStatus.NOT_FOUND, "ruta no encontrada\n")
        return None

    async def _reject(self, connection: ServerConnection, reason: str) -> None:
        logger.warning("hello rechazado: %s", reason)
        await connection.send(json.dumps({"type": "error", "reason": reason}))
        await connection.close(1008, reason)

    async def _handle(self, connection: ServerConnection) -> None:
        try:
            raw = await asyncio.wait_for(
                connection.recv(), self._config.hello_timeout_s
            )
        except TimeoutError:
            await self._reject(connection, "hello_timeout")
            return
        except ConnectionClosed:
            return
        try:
            message = json.loads(raw) if isinstance(raw, str) else None
            hello = parse_hello(message, self._config)
        except (json.JSONDecodeError, HelloRejected) as error:
            await self._reject(
                connection,
                error.reason if isinstance(error, HelloRejected) else "bad_hello",
            )
            return

        previous = self._sessions.get(hello.device_id)
        if previous is not None:
            logger.info(
                "%s se reconectó: se cierra la conexión anterior", hello.device_id
            )
            await previous[1].close(1000, "replaced")
        session = self._factory(hello, WebSocketOutput(connection))
        self._sessions[hello.device_id] = (session, connection)
        await connection.send(json.dumps({"type": "ready"}))
        logger.info("%s conectado", hello.device_id)
        await session.start()
        max_bytes = (
            self._config.max_frames_per_message * hello.frame_samples * BYTES_PER_SAMPLE
        )
        try:
            async for incoming in connection:
                if isinstance(incoming, bytes):
                    if len(incoming) % BYTES_PER_SAMPLE or len(incoming) > max_bytes:
                        logger.warning(
                            "mensaje de audio de %d bytes descartado", len(incoming)
                        )
                        continue
                    await session.on_audio(incoming)
                else:
                    try:
                        data = json.loads(incoming)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict):
                        session.on_json(data)
        except ConnectionClosed:
            pass
        finally:
            if self._sessions.get(hello.device_id, (None, None))[0] is session:
                del self._sessions[hello.device_id]
            await session.close()
            logger.info("%s desconectado", hello.device_id)
