from flask import Blueprint, current_app, jsonify
from shared.application.services import HealthService

shared_api = Blueprint("shared_api", __name__, url_prefix="/api/v1")

@shared_api.get("/health")
def health():
    settings = current_app.config["EDGE_SETTINGS"]
    return jsonify(HealthService().status(settings.edge_id))
