from datetime import UTC, datetime, timedelta

from device_control.domain.entities import Action, DeviceCommand, DeviceType
from device_control.infrastructure.models import InboxModel
from shared.infrastructure.database import unit_of_work


class DispatchDeviceCommand:
    def __init__(
        self, repository, iam_service, command_bus, telemetry, threshold: float
    ):
        self.repository, self.iam = repository, iam_service
        self.command_bus, self.telemetry = command_bus, telemetry
        self.threshold = threshold

    def execute(
        self,
        *,
        source_device_id: str,
        correlation_id: str,
        target_device_id: str,
        action: str,
        confidence: float,
    ) -> DeviceCommand:
        existing = self.repository.find_by_correlation_id(correlation_id)
        if existing:
            return existing
        permission = self.iam.authorize_target(source_device_id, target_device_id)
        command = DeviceCommand.create(
            correlation_id=correlation_id,
            source_device_id=source_device_id,
            target_device_id=target_device_id,
            device_type=DeviceType(permission.device_type),
            action=Action(action),
            confidence=confidence,
            expires_at=datetime.now(UTC) + timedelta(seconds=5),
            threshold=self.threshold,
        ).dispatch()
        payload = self._payload(command)
        with unit_of_work():
            self.repository.save(command)
            self.telemetry.record("command.dispatched", command.command_id, payload)
        self.command_bus.publish(payload)
        return command

    @staticmethod
    def _payload(command: DeviceCommand) -> dict:
        return {
            "command_id": command.command_id,
            "correlation_id": command.correlation_id,
            "source_device_id": command.source_device_id,
            "target_device_id": command.target_device_id,
            "device_type": command.device_type.value,
            "action": command.action.value,
            "issued_at": command.issued_at.isoformat(),
            "expires_at": command.expires_at.isoformat(),
        }


class HandleExecutionResult:
    def __init__(self, repository, telemetry, response_channel):
        self.repository, self.telemetry, self.response_channel = (
            repository,
            telemetry,
            response_channel,
        )

    def execute(self, payload: dict) -> DeviceCommand | None:
        message_id = payload["message_id"]
        if InboxModel.get_or_none(InboxModel.message_id == message_id):
            return None
        command = self.repository.find_by_command_id(payload["command_id"])
        if command is None:
            return None
        updated = (
            command.complete(payload.get("confirmed_state", "UNKNOWN"))
            if payload.get("success")
            else command.fail(payload.get("result_code", "ACTION_FAILED"))
        )
        with unit_of_work():
            InboxModel.create(message_id=message_id, payload=str(payload))
            self.repository.save(updated)
            self.telemetry.record(
                "action.completed" if payload.get("success") else "action.failed",
                updated.command_id,
                payload,
            )
        self.response_channel.send(
            updated.source_device_id,
            {
                "type": "action.completed"
                if payload.get("success")
                else "action.failed",
                "correlation_id": updated.correlation_id,
                "payload": {
                    "command_id": updated.command_id,
                    "confirmed_state": updated.confirmed_state,
                    "result_code": updated.result_code,
                },
            },
        )
        return updated
