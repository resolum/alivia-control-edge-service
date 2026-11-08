import asyncio
import json

from voice_fakes import aio, make_config

from alivia_edge.emergency.notifier import EmergencyNotifier
from alivia_edge.emergency.queue import EmergencyQueue


class FakeTransport:
    """HTTP falso: devuelve los códigos de `script` en orden (o lanza OSError si el elemento es una excepción)."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[tuple[str, dict, dict]] = []

    def post(self, url, body, headers, timeout):
        self.requests.append((url, body, headers))
        outcome = self.script.pop(0) if self.script else 200
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def build(tmp_path, *script, **config):
    cfg = make_config(
        emergency_queue_path=str(tmp_path / "q.db"),
        backend_url="https://backend.test",
        emergency_api_token="real-token",
        emergency_retry_base_s=0.0,
        **config,
    )
    transport = FakeTransport(*script)
    queue = EmergencyQueue(cfg.emergency_queue_path)
    return EmergencyNotifier(cfg, queue, transport), queue, transport


@aio
async def test_payload_headers_and_idempotency(tmp_path):
    notifier, queue, transport = build(tmp_path)
    result = await notifier.notify("alivia-mic-01", "oye alivia ayuda")
    assert result.delivered and queue.pending_count() == 0
    url, body, headers = transport.requests[0]
    assert url == "https://backend.test/api/v1/emergencies"
    assert body["type"] == "emergency" and body["source"] == "voice"
    assert (
        body["deviceId"] == "alivia-mic-01"
        and body["trigger_text"] == "oye alivia ayuda"
    )
    assert body["edge_id"] == "voice-edge-01" and body["timestamp"].endswith("+00:00")
    assert body["emergency_id"] == headers["Idempotency-Key"]
    assert headers["Authorization"] == "Bearer real-token"


@aio
async def test_failure_keeps_the_notice_and_the_retry_loop_delivers_it(tmp_path):
    notifier, queue, transport = build(
        tmp_path, OSError("sin red"), OSError("sin red"), OSError("sin red"), 503
    )
    result = await notifier.notify("mic", "alivia ayuda")
    assert not result.delivered and queue.pending_count() == 1
    assert notifier.health()["last_error"]
    loop_task = asyncio.create_task(notifier.run_forever(poll_s=0.01))
    for _ in range(300):
        if queue.pending_count() == 0:
            break
        await asyncio.sleep(0.01)
    loop_task.cancel()
    assert queue.pending_count() == 0
    ids = {request[1]["emergency_id"] for request in transport.requests}
    assert ids == {
        result.emergency_id
    }  # siempre el mismo id: el cloud puede deduplicar


@aio
async def test_notice_survives_a_restart(tmp_path):
    notifier, _queue, _ = build(tmp_path, OSError("sin red"), OSError("sin red"))
    result = await notifier.notify("mic", "alivia auxilio")
    assert not result.delivered
    reopened = EmergencyQueue(str(tmp_path / "q.db"))
    pending = reopened.due(float("inf"))
    assert [n.emergency_id for n in pending] == [result.emergency_id]
    assert pending[0].payload["trigger_text"] == "alivia auxilio"


@aio
async def test_duplicate_conflict_counts_as_delivered(tmp_path):
    notifier, _queue, _ = build(tmp_path, 409)
    assert (await notifier.notify("mic", "alivia ayuda")).delivered


@aio
async def test_cancellation_is_sent_after_the_emergency_and_marks_it_not_deletes_it(
    tmp_path,
):
    notifier, queue, transport = build(tmp_path)
    result = await notifier.notify("mic", "alivia ayuda")
    await notifier.cancel(result.emergency_id)
    await asyncio.sleep(0.05)
    kinds = [request[1]["type"] for request in transport.requests]
    assert kinds == ["emergency", "emergency_cancelled"]
    assert transport.requests[1][1] == {
        "type": "emergency_cancelled",
        "emergency_id": result.emergency_id,
    }
    assert queue.pending_count() == 0


@aio
async def test_cancellation_waits_while_the_emergency_is_still_undelivered(tmp_path):
    notifier, queue, transport = build(tmp_path, OSError("x"), OSError("x"))
    result = await notifier.notify("mic", "alivia ayuda")
    await notifier.cancel(result.emergency_id)
    await asyncio.sleep(0.05)
    assert [r[1]["type"] for r in transport.requests] == [
        "emergency",
        "emergency",
    ]  # la cancelación no se adelanta
    assert queue.pending_count() == 2


def test_placeholder_is_reported_as_not_configured(tmp_path):
    cfg = make_config(emergency_queue_path=str(tmp_path / "q.db"))
    notifier = EmergencyNotifier(cfg, EmergencyQueue(cfg.emergency_queue_path))
    assert not notifier.configured
    assert notifier.health()["state"] == "placeholder / no configurado"


def test_real_settings_are_configured_and_health_shows_pending(tmp_path):
    notifier, queue, _ = build(tmp_path)
    assert notifier.configured and notifier.health()["state"] == "ok"
    queue.add("e1", "emergency", {"a": 1}, 0.0)
    assert notifier.health()["pending"] == 1


def test_token_changeme_or_example_host_are_placeholders():
    assert make_config(
        backend_url="https://api.alivia.example", emergency_api_token="real"
    ).emergency_is_placeholder
    assert make_config(
        backend_url="https://api.real.com", emergency_api_token="changeme"
    ).emergency_is_placeholder
    assert not make_config(
        backend_url="https://api.real.com", emergency_api_token="tok"
    ).emergency_is_placeholder
    assert json.dumps(
        make_config().backend_url
    )  # el valor por defecto es el placeholder .example
