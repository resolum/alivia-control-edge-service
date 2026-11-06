import json
from typing import Callable
import paho.mqtt.client as mqtt

class InMemoryCommandBus:
    """Useful for tests and local development without a broker."""
    def __init__(self):
        self.messages: list[dict] = []
    def publish(self, payload: dict) -> None:
        self.messages.append(payload)

class MqttCommandBus:
    def __init__(self, host: str, port: int, network_id: str,
                 result_handler: Callable[[dict], None]):
        self.host, self.port, self.network_id = host, port, network_id
        self.result_handler = result_handler
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    @property
    def command_topic(self) -> str:
        return f"alivia/v1/networks/{self.network_id}/actuator-edge/commands"
    @property
    def result_topic(self) -> str:
        return f"alivia/v1/networks/{self.network_id}/control-edge/results"

    def start(self) -> None:
        self.client.connect_async(self.host, self.port)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, payload: dict) -> None:
        info = self.client.publish(self.command_topic, json.dumps(payload), qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with code {info.rc}")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(self.result_topic, qos=1)

    def _on_message(self, client, userdata, message):
        self.result_handler(json.loads(message.payload.decode("utf-8")))
