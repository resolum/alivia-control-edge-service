"""Tabla única de dispositivos controlables. Lo que no está aquí se descarta."""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ActionSpec:
    """Una acción de un dispositivo y las frases de voz asociadas (plantillas fijas, nunca del LLM)."""

    api_action: (
        str  # valor que entiende el edge de actuadores (OPEN, CLOSE, TURN_ON, TURN_OFF)
    )
    confirm: str  # "abra la puerta" -> "¿Quieres que abra la puerta?"
    progress: str  # "Abriendo la puerta"
    done: str  # "la puerta está abierta"
    infinitive: str  # "abrir la puerta"


@dataclass(frozen=True)
class DeviceSpec:
    name: str  # nombre que ve el LLM, p. ej. "puerta"
    device_id: str  # id del dispositivo en el edge de actuadores
    device_type: str  # DOOR | WINDOW | LIGHT
    actions: dict[str, ActionSpec] = field(default_factory=dict)


DEFAULT_DEVICES = (
    DeviceSpec(
        "puerta",
        "door-01",
        "DOOR",
        {
            "open": ActionSpec(
                "OPEN",
                "abra la puerta",
                "Abriendo la puerta",
                "la puerta está abierta",
                "abrir la puerta",
            ),
            "close": ActionSpec(
                "CLOSE",
                "cierre la puerta",
                "Cerrando la puerta",
                "la puerta está cerrada",
                "cerrar la puerta",
            ),
        },
    ),
    DeviceSpec(
        "ventana",
        "window-01",
        "WINDOW",
        {
            "open": ActionSpec(
                "OPEN",
                "abra la ventana",
                "Abriendo la ventana",
                "la ventana está abierta",
                "abrir la ventana",
            ),
            "close": ActionSpec(
                "CLOSE",
                "cierre la ventana",
                "Cerrando la ventana",
                "la ventana está cerrada",
                "cerrar la ventana",
            ),
        },
    ),
    DeviceSpec(
        "luz_cuarto",
        "light-01",
        "LIGHT",
        {
            "on": ActionSpec(
                "TURN_ON",
                "encienda la luz del cuarto",
                "Encendiendo la luz del cuarto",
                "la luz del cuarto está encendida",
                "encender la luz del cuarto",
            ),
            "off": ActionSpec(
                "TURN_OFF",
                "apague la luz del cuarto",
                "Apagando la luz del cuarto",
                "la luz del cuarto está apagada",
                "apagar la luz del cuarto",
            ),
        },
    ),
)

STATE_LABELS = {
    "OPEN": "abierta",
    "CLOSED": "cerrada",
    "CLOSE": "cerrada",
    "ON": "encendida",
    "OFF": "apagada",
}


class UnknownDeviceAction(ValueError):
    pass


class DeviceCatalog:
    def __init__(self, devices: tuple[DeviceSpec, ...] = DEFAULT_DEVICES):
        self._devices = {device.name: device for device in devices}

    @classmethod
    def from_file(cls, path: str | None) -> "DeviceCatalog":
        """Carga la tabla desde un JSON (lista de dispositivos); sin ruta usa la tabla por defecto."""
        if not path:
            return cls()
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        devices = tuple(
            DeviceSpec(
                item["name"],
                item["device_id"],
                item["device_type"],
                {key: ActionSpec(**spec) for key, spec in item["actions"].items()},
            )
            for item in raw
        )
        return cls(devices)

    @property
    def devices(self) -> tuple[DeviceSpec, ...]:
        return tuple(self._devices.values())

    def resolve(self, device: str, action: str) -> tuple[DeviceSpec, ActionSpec]:
        spec = self._devices.get(device)
        if spec is None:
            raise UnknownDeviceAction(f"dispositivo desconocido: {device!r}")
        action_spec = spec.actions.get(action)
        if action_spec is None:
            raise UnknownDeviceAction(f"acción {action!r} no permitida en {device!r}")
        return spec, action_spec

    def all_phrases(self) -> list[str]:
        """Todas las frases fijas que Piper dirá para los dispositivos (para precalentar la caché y los tests)."""
        phrases: list[str] = []
        for device in self.devices:
            for action in device.actions.values():
                phrases += [
                    f"¿Quieres que {action.confirm}?",
                    action.progress,
                    f"Listo, {action.done}",
                    f"No pude {action.infinitive}",
                    f"No pude confirmar que se completó: {action.infinitive}",
                ]
        return phrases


class DeviceStates:
    """Último estado confirmado por el edge de actuadores, para el prompt del LLM."""

    def __init__(self, catalog: DeviceCatalog):
        self._states = {device.name: "desconocido" for device in catalog.devices}

    def update(self, name: str, confirmed_state: str | None) -> None:
        if name in self._states and confirmed_state:
            self._states[name] = STATE_LABELS.get(
                confirmed_state.upper(), confirmed_state.lower()
            )

    def snapshot(self) -> dict[str, str]:
        return dict(self._states)
