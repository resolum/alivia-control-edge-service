"""Edge de actuadores falso: escucha los comandos por MQTT y responde ok, error o nada (timeout).

Uso:
    python -m scripts.mock_actuators --mode ok            # confirma todo
    python -m scripts.mock_actuators --mode error         # falla con ACTION_FAILED
    python -m scripts.mock_actuators --mode timeout       # no responde nunca
"""

import argparse
import json
import time
import uuid

import paho.mqtt.client as mqtt

from alivia_edge.config import VoiceConfig

CONFIRMED = {"OPEN": "OPEN", "CLOSE": "CLOSED", "TURN_ON": "ON", "TURN_OFF": "OFF"}


def result_for(command: dict, mode: str) -> dict | None:
    if mode == "timeout":
        return None
    ok = mode == "ok"
    return {
        "message_id": str(uuid.uuid4()),
        "command_id": command["command_id"],
        "success": ok,
        "confirmed_state": CONFIRMED.get(command["action"]) if ok else None,
        "result_code": None if ok else "ACTION_FAILED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=["ok", "error", "timeout"], default="ok")
    parser.add_argument(
        "--delay", type=float, default=0.5, help="segundos antes de responder"
    )
    args = parser.parse_args()
    config = VoiceConfig.from_env()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = lambda c, u, f, rc, p: c.subscribe(config.command_topic, qos=1)

    def on_message(c, userdata, message):
        command = json.loads(message.payload)
        print(
            f"comando: {command['action']} -> {command['target_device_id']} (modo {args.mode})"
        )
        result = result_for(command, args.mode)
        if result:
            time.sleep(args.delay)
            c.publish(config.result_topic, json.dumps(result), qos=1)
            print(f"resultado: {result['success']} {result['confirmed_state']}")

    client.on_message = on_message
    client.connect(config.mqtt_host, config.mqtt_port)
    print(f"escuchando {config.command_topic} en {config.mqtt_host}:{config.mqtt_port}")
    client.loop_forever()


if __name__ == "__main__":
    main()
