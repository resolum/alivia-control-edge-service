"""Estado del pipeline de voz para /health y /status.

El pipeline corre en su propio proceso asyncio y escribe una instantánea JSON de forma atómica; el
servicio Flask existente solo la lee (ver `alivia_edge/http_status.py`). Así no hay IPC ni estado compartido.
"""

import asyncio
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from alivia_edge.config import VoiceConfig
from alivia_edge.emergency.notifier import EmergencyNotifier


class StatusReporter:
    def __init__(
        self,
        config: VoiceConfig,
        notifier: EmergencyNotifier,
        sessions: Callable[[], list[dict]],
        mqtt_connected: Callable[[], bool] = lambda: False,
    ):
        self._config = config
        self._notifier = notifier
        self._sessions = sessions
        self._mqtt_connected = mqtt_connected
        self._started = time.time()

    def snapshot(self) -> dict:
        emergency = self._notifier.health()
        return {
            "service": "alivia-voice-edge",
            "edge_id": self._config.edge_id,
            "status": "ok" if emergency["state"] == "ok" else "degraded",
            "updated_at": time.time(),
            "uptime_s": round(time.time() - self._started),
            "sessions": self._sessions(),
            "mqtt": {"connected": self._mqtt_connected()},
            "emergency": emergency,
        }

    def write(self) -> None:
        path = Path(self._config.status_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.snapshot()), encoding="utf-8")
        os.replace(temporary, path)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, self.write)
            await asyncio.sleep(self._config.status_interval_s)
