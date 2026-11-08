from flask import Blueprint, current_app, jsonify

telemetry_api = Blueprint("telemetry_api", __name__, url_prefix="/api/v1/telemetry")


@telemetry_api.post("/sync")
def synchronize():
    count = current_app.extensions["telemetry_synchronizer"].synchronize()
    return jsonify(synchronized=count)
