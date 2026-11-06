from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

class DeviceType(StrEnum):
    DOOR = "DOOR"
    WINDOW = "WINDOW"
    LIGHT = "LIGHT"

class Action(StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    TURN_ON = "TURN_ON"
    TURN_OFF = "TURN_OFF"
    GET_STATE = "GET_STATE"

class ExecutionStatus(StrEnum):
    VALIDATED = "VALIDATED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class DomainError(ValueError):
    code = "DOMAIN_ERROR"
class LowConfidenceError(DomainError):
    code = "LOW_CONFIDENCE"
class InvalidDeviceActionError(DomainError):
    code = "INVALID_DEVICE_ACTION"
class InvalidStatusTransitionError(DomainError):
    code = "INVALID_STATUS_TRANSITION"

ALLOWED_ACTIONS = {
    DeviceType.DOOR: {Action.OPEN, Action.CLOSE, Action.GET_STATE},
    DeviceType.WINDOW: {Action.OPEN, Action.CLOSE, Action.GET_STATE},
    DeviceType.LIGHT: {Action.TURN_ON, Action.TURN_OFF, Action.GET_STATE},
}

@dataclass(frozen=True)
class DeviceCommand:
    command_id: str
    correlation_id: str
    source_device_id: str
    target_device_id: str
    device_type: DeviceType
    action: Action
    confidence: float
    status: ExecutionStatus
    issued_at: datetime
    expires_at: datetime
    result_code: str | None = None
    confirmed_state: str | None = None

    @classmethod
    def create(cls, *, correlation_id: str, source_device_id: str,
               target_device_id: str, device_type: DeviceType, action: Action,
               confidence: float, expires_at: datetime, threshold: float) -> "DeviceCommand":
        if confidence < threshold:
            raise LowConfidenceError(f"Confidence {confidence:.2f} is below {threshold:.2f}")
        if action not in ALLOWED_ACTIONS[device_type]:
            raise InvalidDeviceActionError(f"{action} is not valid for {device_type}")
        return cls(str(uuid4()), correlation_id, source_device_id, target_device_id,
                   device_type, action, confidence, ExecutionStatus.VALIDATED,
                   datetime.now(timezone.utc), expires_at)

    def dispatch(self) -> "DeviceCommand":
        if self.status != ExecutionStatus.VALIDATED:
            raise InvalidStatusTransitionError("Only a validated command can be dispatched")
        return replace(self, status=ExecutionStatus.DISPATCHED)

    def complete(self, confirmed_state: str) -> "DeviceCommand":
        if self.status != ExecutionStatus.DISPATCHED:
            raise InvalidStatusTransitionError("Only a dispatched command can complete")
        return replace(self, status=ExecutionStatus.COMPLETED, confirmed_state=confirmed_state)

    def fail(self, result_code: str) -> "DeviceCommand":
        if self.status != ExecutionStatus.DISPATCHED:
            raise InvalidStatusTransitionError("Only a dispatched command can fail")
        return replace(self, status=ExecutionStatus.FAILED, result_code=result_code)
