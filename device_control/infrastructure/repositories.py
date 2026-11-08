from device_control.domain.entities import (
    Action,
    DeviceCommand,
    DeviceType,
    ExecutionStatus,
)
from device_control.infrastructure.models import DeviceCommandModel


class PeeweeDeviceCommandRepository:
    def save(self, command: DeviceCommand) -> None:
        DeviceCommandModel.insert(
            command_id=command.command_id,
            correlation_id=command.correlation_id,
            source_device_id=command.source_device_id,
            target_device_id=command.target_device_id,
            device_type=command.device_type.value,
            action=command.action.value,
            confidence=command.confidence,
            status=command.status.value,
            issued_at=command.issued_at,
            expires_at=command.expires_at,
            result_code=command.result_code,
            confirmed_state=command.confirmed_state,
        ).on_conflict(
            conflict_target=[DeviceCommandModel.command_id],
            update={
                DeviceCommandModel.status: command.status.value,
                DeviceCommandModel.result_code: command.result_code,
                DeviceCommandModel.confirmed_state: command.confirmed_state,
            },
        ).execute()

    def find_by_command_id(self, command_id: str) -> DeviceCommand | None:
        row = DeviceCommandModel.get_or_none(
            DeviceCommandModel.command_id == command_id
        )
        return self._to_domain(row) if row else None

    def find_by_correlation_id(self, correlation_id: str) -> DeviceCommand | None:
        row = DeviceCommandModel.get_or_none(
            DeviceCommandModel.correlation_id == correlation_id
        )
        return self._to_domain(row) if row else None

    @staticmethod
    def _to_domain(row: DeviceCommandModel) -> DeviceCommand:
        return DeviceCommand(
            row.command_id,
            row.correlation_id,
            row.source_device_id,
            row.target_device_id,
            DeviceType(row.device_type),
            Action(row.action),
            row.confidence,
            ExecutionStatus(row.status),
            row.issued_at,
            row.expires_at,
            row.result_code,
            row.confirmed_state,
        )
