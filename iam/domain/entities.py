from dataclasses import dataclass

@dataclass(frozen=True)
class DevicePermission:
    target_device_id: str
    device_type: str
