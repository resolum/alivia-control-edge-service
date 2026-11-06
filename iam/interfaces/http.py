from flask import Blueprint, current_app, jsonify, request
from iam.infrastructure.models import AuthorizedNodeModel, DevicePermissionModel

iam_api = Blueprint("iam_api", __name__, url_prefix="/api/v1/iam")

def require_setup_token() -> None:
    if request.headers.get("X-Setup-Token") != current_app.config["EDGE_SETTINGS"].setup_token:
        raise PermissionError("Invalid setup token")

@iam_api.post("/nodes")
def register_node():
    require_setup_token()
    data = request.get_json(force=True)
    AuthorizedNodeModel.insert(node_id=data["node_id"], api_key=data["api_key"],
        node_type=data.get("node_type", "MICROPHONE"), active=True).on_conflict_replace().execute()
    return jsonify(node_id=data["node_id"]), 201

@iam_api.post("/permissions")
def register_permission():
    require_setup_token()
    data = request.get_json(force=True)
    DevicePermissionModel.insert(source_node_id=data["source_node_id"],
        target_device_id=data["target_device_id"], device_type=data["device_type"],
        active=True).on_conflict_replace().execute()
    return jsonify(source_node_id=data["source_node_id"],
                   target_device_id=data["target_device_id"]), 201
