"""Aviso de emergencia al cloud por HTTPS. Es el único tráfico a Internet del edge y nunca pasa por MQTT."""

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from alivia_edge.config import VoiceConfig
from alivia_edge.emergency.queue import CANCEL, EMERGENCY, EmergencyQueue, Notice

logger = logging.getLogger(__name__)

IDEMPOTENT_DUPLICATE = 409


class HttpTransport(Protocol):
    def post(
        self, url: str, body: dict, headers: dict[str, str], timeout: float
    ) -> int:
        """Devuelve el código HTTP. Lanza OSError si no hay red."""


class UrllibTransport:
    def post(
        self, url: str, body: dict, headers: dict[str, str], timeout: float
    ) -> int:
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code


@dataclass(frozen=True)
class NotifyResult:
    emergency_id: str
    delivered: bool


class EmergencyNotifier:
    def __init__(
        self,
        config: VoiceConfig,
        queue: EmergencyQueue,
        transport: HttpTransport | None = None,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._config = config
        self._queue = queue
        self._transport = transport or UrllibTransport()
        self._wall_clock = wall_clock
        self._send_lock = asyncio.Lock()
        self._last_success_at: float | None = None

    @property
    def configured(self) -> bool:
        return not self._config.emergency_is_placeholder

    def health(self) -> dict:
        pending = self._queue.pending_count()
        last_error = self._queue.last_error()
        if not self.configured:
            state = "placeholder / no configurado"
        elif last_error:
            state = "degradado"
        else:
            state = "ok"
        return {
            "state": state,
            "pending": pending,
            "last_error": last_error,
            "last_success_at": self._last_success_at,
        }

    async def notify(
        self,
        device_id: str,
        trigger_text: str,
        on_registered: Callable[[str], None] | None = None,
    ) -> NotifyResult:
        """Guarda el aviso en disco, intenta enviarlo y, si falla, queda en la cola para el reintento."""
        emergency_id = str(uuid.uuid4())
        payload = {
            "emergency_id": emergency_id,
            "type": "emergency",
            "source": "voice",
            "deviceId": device_id,
            "trigger_text": trigger_text,
            "timestamp": datetime.fromtimestamp(self._wall_clock(), UTC).isoformat(),
            "edge_id": self._config.edge_id,
        }
        await self._to_thread(
            self._queue.add, emergency_id, EMERGENCY, payload, self._wall_clock()
        )
        if on_registered:
            on_registered(emergency_id)
        # El envío es propiedad del notificador: una desconexión del ESP32 no lo cancela.
        delivery = asyncio.create_task(self._deliver_inline(emergency_id, EMERGENCY))
        return NotifyResult(emergency_id, await asyncio.shield(delivery))

    async def cancel(self, emergency_id: str) -> None:
        """Marca el aviso como cancelado en el cloud (no lo borra: decide el cuidador)."""
        payload = {"type": "emergency_cancelled", "emergency_id": emergency_id}
        await self._to_thread(
            self._queue.add, emergency_id, CANCEL, payload, self._wall_clock()
        )
        asyncio.create_task(self._deliver_inline(emergency_id, CANCEL))

    async def run_forever(self, poll_s: float = 2.0) -> None:
        """Reintenta sin parar los avisos pendientes hasta que el cloud los confirme."""
        while True:
            for notice in await self._to_thread(self._queue.due, self._wall_clock()):
                await self._send(notice)
            await asyncio.sleep(poll_s)

    async def _deliver_inline(self, emergency_id: str, kind: str) -> bool:
        for attempt in range(self._config.emergency_inline_attempts):
            notice = await self._to_thread(self._queue.get_unsent, emergency_id, kind)
            if notice is None:
                return True  # ya confirmado
            if kind == CANCEL and await self._to_thread(
                self._queue.get_unsent, emergency_id, EMERGENCY
            ):
                return False  # la cancelación espera a que el aviso original llegue
            if await self._send(notice):
                return True
            if attempt + 1 < self._config.emergency_inline_attempts:
                await asyncio.sleep(0.5)
        return False

    async def _send(self, notice: Notice) -> bool:
        cfg = self._config
        url = cfg.backend_url.rstrip("/") + cfg.emergency_path
        key = (
            notice.emergency_id
            if notice.kind == EMERGENCY
            else f"{notice.emergency_id}:cancel"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.emergency_api_token}",
            "Idempotency-Key": key,
        }
        async with self._send_lock:
            try:
                status = await self._to_thread(
                    self._transport.post,
                    url,
                    notice.payload,
                    headers,
                    cfg.emergency_timeout_s,
                )
                error = (
                    None
                    if 200 <= status < 300 or status == IDEMPOTENT_DUPLICATE
                    else f"HTTP {status}"
                )
            except OSError as exc:
                error = f"sin conexión: {exc}"
            now = self._wall_clock()
            if error is None:
                await self._to_thread(
                    self._queue.mark_sent, notice.emergency_id, notice.kind, now
                )
                self._last_success_at = now
                logger.info(
                    "aviso %s (%s) confirmado por el cloud",
                    notice.emergency_id,
                    notice.kind,
                )
                return True
            delay = min(
                cfg.emergency_retry_max_s,
                cfg.emergency_retry_base_s * 2**notice.attempts,
            )
            await self._to_thread(
                self._queue.mark_failed,
                notice.emergency_id,
                notice.kind,
                error,
                now + delay,
            )
            logger.warning(
                "aviso %s (%s) no enviado: %s; reintento en %.0f s",
                notice.emergency_id,
                notice.kind,
                error,
                delay,
            )
            return False

    @staticmethod
    async def _to_thread(function, *args):
        return await asyncio.get_running_loop().run_in_executor(None, function, *args)
