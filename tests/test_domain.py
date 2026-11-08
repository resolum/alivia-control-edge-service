from datetime import UTC, datetime, timedelta

import pytest

from device_control.domain.entities import (
    Action,
    DeviceCommand,
    DeviceType,
    ExecutionStatus,
    InvalidDeviceActionError,
    LowConfidenceError,
)


def make_command(**overrides):
    values = {
        "correlation_id": "corr-1",
        "source_device_id": "mic-1",
        "target_device_id": "door-1",
        "device_type": DeviceType.DOOR,
        "action": Action.OPEN,
        "confidence": 0.90,
        "expires_at": datetime.now(UTC) + timedelta(seconds=5),
        "threshold": 0.75,
    }
    values.update(overrides)
    return DeviceCommand.create(**values)


def test_command_follows_happy_path():
    command = make_command().dispatch().complete("OPEN")
    assert command.status == ExecutionStatus.COMPLETED
    assert command.confirmed_state == "OPEN"


def test_low_confidence_is_rejected():
    with pytest.raises(LowConfidenceError):
        make_command(confidence=0.50)


def test_invalid_action_for_device_is_rejected():
    with pytest.raises(InvalidDeviceActionError):
        make_command(device_type=DeviceType.LIGHT, action=Action.OPEN)
