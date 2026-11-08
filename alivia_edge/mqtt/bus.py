"""Publicación de comandos al edge de actuadores por MQTT (QoS 1) y espera del resultado real.

Usa el mismo contrato de mensajes y topics que `device_control.infrastructure.messaging`.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from alivia_edge.config import VoiceConfig
from alivia_edge.devices.catalog import ActionSpec, DeviceSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActuatorResult:
    command_id: str
    status: str  # ok | error | timeout
    confirmed_state: str | None = None
    result_code: str | None = None


class ActuatorBus(Protocol):
    async def execute(
        self, *, source_device_id: str, spec: DeviceSpec, action: ActionSpec
    ) -> ActuatorResult: ...


class PahoActuatorBus:
    def __init__(self, config: VoiceConfig):
        import paho.mqtt.client as mqtt

        self._config = config
        self._mqtt = mqtt
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._waiting: dict[str, asyncio.Future[dict]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._client.connect_async(self._config.mqtt_host, self._config.mqtt_port)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    @property
    def connected(self) -> bool:
        return self._client.is_connected()

    async def execute(
        self, *, source_device_id: str, spec: DeviceSpec, action: ActionSpec
    ) -> ActuatorResult:
        command_id = str(uuid.uuid4())
        issued = datetime.now(UTC)
        payload = {
            "command_id": command_id,
            "correlation_id": command_id,
            "source_device_id": source_device_id,
            "target_device_id": spec.device_id,
            "device_type": spec.device_type,
            "action": action.api_action,
            "issued_at": issued.isoformat(),
            "expires_at": (
                issued + timedelta(seconds=self._config.actuator_timeout_s)
            ).isoformat(),
        }
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._waiting[command_id] = future
        try:
            info = self._client.publish(
                self._config.command_topic, json.dumps(payload), qos=1
            )
            if info.rc != self._mqtt.MQTT_ERR_SUCCESS:
                return ActuatorResult(
                    command_id, "error", result_code="MQTT_UNAVAILABLE"
                )
            result = await asyncio.wait_for(future, self._config.actuator_timeout_s)
        except TimeoutError:
            return ActuatorResult(command_id, "timeout")
        finally:
            self._waiting.pop(command_id, None)
        if result.get("success"):
            return ActuatorResult(command_id, "ok", result.get("confirmed_state"))
        return ActuatorResult(
            command_id,
            "error",
            result.get("confirmed_state"),
            result.get("result_code"),
        )

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(self._config.result_topic, qos=1)

    def _on_message(self, client, userdata, message):
        try:
            result = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("resultado MQTT ilegible descartado")
            return
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._resolve, result)

    def _resolve(self, result: dict) -> None:
        future = self._waiting.get(result.get("command_id", ""))
        if future is not None and not future.done():
            future.set_result(result)
