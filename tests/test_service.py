from config import Settings
from bootstrap import create_app

def build_app(tmp_path):
    return create_app(Settings(database_path=str(tmp_path / "test.db"), mqtt_enabled=False,
                               setup_token="test-setup-token"))

def provision(client):
    headers = {"X-Setup-Token": "test-setup-token"}
    assert client.post("/api/v1/iam/nodes", json={
        "node_id": "mic-1", "api_key": "secret", "node_type": "MICROPHONE"
    }, headers=headers).status_code == 201
    assert client.post("/api/v1/iam/permissions", json={
        "source_node_id": "mic-1", "target_device_id": "door-1", "device_type": "DOOR"
    }, headers=headers).status_code == 201

def test_dispatches_an_authorized_command(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    provision(client)
    command = app.extensions["dispatch_service"].execute(
        source_device_id="mic-1", correlation_id="corr-1",
        target_device_id="door-1", action="OPEN", confidence=0.91)
    assert command.status.value == "DISPATCHED"
    assert len(app.extensions["command_bus"].messages) == 1
    response = client.get(f"/api/v1/commands/{command.command_id}")
    assert response.status_code == 200
    assert response.json["status"] == "DISPATCHED"

def test_result_is_idempotent(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    provision(client)
    command = app.extensions["dispatch_service"].execute(
        source_device_id="mic-1", correlation_id="corr-2",
        target_device_id="door-1", action="OPEN", confidence=0.91)
    payload = {"message_id": "result-1", "command_id": command.command_id,
               "success": True, "confirmed_state": "OPEN"}
    first = app.extensions["result_service"].execute(payload)
    second = app.extensions["result_service"].execute(payload)
    assert first.status.value == "COMPLETED"
    assert second is None

def test_health_endpoint(tmp_path):
    response = build_app(tmp_path).test_client().get("/api/v1/health")
    assert response.status_code == 200
    assert response.json["status"] == "UP"

def test_swagger_documentation_is_available(tmp_path):
    client = build_app(tmp_path).test_client()
    assert client.get("/apidocs/").status_code == 200
    specification = client.get("/apispec_1.json")
    assert specification.status_code == 200
    assert "/iam/nodes" in specification.json["paths"]
