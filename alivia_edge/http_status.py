"""`/health` y `/status` del pipeline de voz, dentro del servicio Flask existente."""

import json
import time
from pathlib import Path

from flask import Blueprint, current_app, jsonify

from alivia_edge.config import VoiceConfig

voice_status_api = Blueprint("voice_status_api", __name__)

STALE_AFTER_S = 15


def _load() -> tuple[dict | None, str]:
    path = Path(
        current_app.config.get("VOICE_STATUS_PATH")
        or VoiceConfig.from_env().status_path
    )
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "el pipeline de voz no ha publicado su estado"
    if time.time() - snapshot.get("updated_at", 0) > STALE_AFTER_S:
        return None, "el estado del pipeline de voz está desactualizado"
    return snapshot, ""


@voice_status_api.get("/status")
def status():
    snapshot, reason = _load()
    if snapshot is None:
        return jsonify(status="down", reason=reason), 503
    return jsonify(snapshot)


@voice_status_api.get("/health")
def health():
    snapshot, reason = _load()
    if snapshot is None:
        return jsonify(status="down", reason=reason), 503
    return jsonify(status=snapshot["status"], emergency=snapshot["emergency"])
