import asyncio
import json

from voice_fakes import aio, make_config

from alivia_edge.devices.catalog import DeviceCatalog
from alivia_edge.mqtt.bus import PahoActuatorBus

SPEC = DeviceCatalog().devices[0]
OPEN = SPEC.actions["open"]


class FakeInfo:
    def __init__(self, rc):
        self.rc = rc


class FakeMqttClient:
    def __init__(self, rc=0):
        self.rc, self.published = rc, []

    def publish(self, topic, payload, qos):
        self.published.append((topic, json.loads(payload), qos))
        return FakeInfo(self.rc)


def make_bus(rc=0):
    bus = PahoActuatorBus(make_config(actuator_timeout_s=0.1))
    bus._loop = asyncio.get_running_loop()
    bus._client = FakeMqttClient(rc)
    return bus


def answer(bus, **fields):
    _topic, payload, _ = bus._client.published[0]
    message = {"message_id": "m1", "command_id": payload["command_id"], **fields}
    bus._on_message(
        None, None, type("Msg", (), {"payload": json.dumps(message).encode()})
    )


@aio
async def test_publishes_qos1_command_in_the_existing_contract_and_waits_for_the_result():
    bus = make_bus()
    task = asyncio.create_task(
        bus.execute(source_device_id="esp32-1", spec=SPEC, action=OPEN)
    )
    await asyncio.sleep(0.01)
    topic, payload, qos = bus._client.published[0]
    assert (
        topic == "alivia/v1/networks/local-network/actuator-edge/commands" and qos == 1
    )
    assert payload["target_device_id"] == "door-01" and payload["action"] == "OPEN"
    assert payload["device_type"] == "DOOR" and payload["source_device_id"] == "esp32-1"
    answer(bus, success=True, confirmed_state="OPEN")
    result = await task
    assert (result.status, result.confirmed_state) == ("ok", "OPEN")


@aio
async def test_error_result_and_timeout():
    bus = make_bus()
    task = asyncio.create_task(
        bus.execute(source_device_id="e", spec=SPEC, action=OPEN)
    )
    await asyncio.sleep(0.01)
    answer(bus, success=False, result_code="JAMMED")
    assert (await task).status == "error"
    assert (
        await bus.execute(source_device_id="e", spec=SPEC, action=OPEN)
    ).status == "timeout"


@aio
async def test_publish_failure_is_reported_immediately():
    result = await make_bus(rc=4).execute(source_device_id="e", spec=SPEC, action=OPEN)
    assert (result.status, result.result_code) == ("error", "MQTT_UNAVAILABLE")


@aio
async def test_unknown_or_garbled_results_are_ignored():
    bus = make_bus()
    bus._on_message(None, None, type("Msg", (), {"payload": b"\xff\xfe"}))
    bus._on_message(None, None, type("Msg", (), {"payload": b'{"command_id": "otro"}'}))
    await asyncio.sleep(0.01)
