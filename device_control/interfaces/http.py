from flask import Blueprint, jsonify

from device_control.infrastructure.models import DeviceCommandModel

device_control_api = Blueprint(
    "device_control_api", __name__, url_prefix="/api/v1/commands"
)


@device_control_api.get("/<command_id>")
def get_command(command_id: str):
    row = DeviceCommandModel.get_or_none(DeviceCommandModel.command_id == command_id)
    if row is None:
        return jsonify(code="COMMAND_NOT_FOUND"), 404
    return jsonify(
        command_id=row.command_id,
        correlation_id=row.correlation_id,
        target_device_id=row.target_device_id,
        device_type=row.device_type,
        action=row.action,
        status=row.status,
        result_code=row.result_code,
        confirmed_state=row.confirmed_state,
    )
