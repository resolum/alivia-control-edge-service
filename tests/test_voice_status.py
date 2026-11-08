import json
import time

from voice_fakes import make_config

from alivia_edge.emergency.notifier import EmergencyNotifier
from alivia_edge.emergency.queue import EmergencyQueue
from alivia_edge.mqtt.bus import PahoActuatorBus
from alivia_edge.status import StatusReporter
from bootstrap import create_app
from config import Settings


def app_with_status(tmp_path, snapshot=None):
    status = tmp_path / "status.json"
    if snapshot is not None:
        status.write_text(json.dumps(snapshot))
    app = create_app(Settings(database_path=str(tmp_path / "t.db"), mqtt_enabled=False))
    app.config["VOICE_STATUS_PATH"] = str(status)
    return app.test_client()


def snapshot(**changes):
    base = {
        "status": "ok",
        "updated_at": time.time(),
        "emergency": {"state": "ok", "pending": 0, "last_error": None},
    }
    return {**base, **changes}


def test_health_and_status_report_the_pipeline(tmp_path):
    client = app_with_status(tmp_path, snapshot())
    assert client.get("/health").json == {
        "status": "ok",
        "emergency": {"state": "ok", "pending": 0, "last_error": None},
    }
    assert client.get("/status").json["status"] == "ok"


def test_placeholder_emergency_path_is_visible(tmp_path):
    emergency = {
        "state": "placeholder / no configurado",
        "pending": 3,
        "last_error": None,
    }
    client = app_with_status(tmp_path, snapshot(status="degraded", emergency=emergency))
    body = client.get("/health").json
    assert body["status"] == "degraded" and body["emergency"]["pending"] == 3
    assert "placeholder" in body["emergency"]["state"]


def test_missing_or_stale_status_means_down(tmp_path):
    assert app_with_status(tmp_path).get("/health").status_code == 503
    stale = app_with_status(tmp_path / "..", snapshot(updated_at=time.time() - 60)).get(
        "/status"
    )
    assert stale.status_code == 503 and stale.json["status"] == "down"


def test_existing_health_endpoint_is_untouched(tmp_path):
    assert app_with_status(tmp_path).get("/api/v1/health").status_code == 200


def test_reporter_writes_snapshot_atomically(tmp_path):
    cfg = make_config(
        emergency_queue_path=str(tmp_path / "q.db"),
        status_path=str(tmp_path / "out" / "status.json"),
    )
    queue = EmergencyQueue(cfg.emergency_queue_path)
    queue.add("e1", "emergency", {}, 0.0)
    reporter = StatusReporter(
        cfg, EmergencyNotifier(cfg, queue), lambda: [{"deviceId": "x"}], lambda: True
    )
    reporter.write()
    written = json.loads((tmp_path / "out" / "status.json").read_text())
    assert written["status"] == "degraded"  # el camino de emergencia es placeholder
    assert written["emergency"]["pending"] == 1 and written["sessions"] == [
        {"deviceId": "x"}
    ]
    assert written["mqtt"] == {"connected": True}


def test_mqtt_bus_defaults_to_existing_topic_contract():
    cfg = make_config(network_id="casa")
    assert cfg.command_topic == "alivia/v1/networks/casa/actuator-edge/commands"
    assert cfg.result_topic == "alivia/v1/networks/casa/control-edge/results"
    assert PahoActuatorBus(cfg).connected is False
