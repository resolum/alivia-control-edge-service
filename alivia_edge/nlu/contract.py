"""Contrato JSON del LLM y su validación. El edge nunca confía en la salida del modelo."""

import json
from dataclasses import dataclass

from alivia_edge.devices.catalog import DeviceCatalog, UnknownDeviceAction

PROPOSE = "propose"
CLARIFY = "clarify"
MAX_SPEECH_WORDS = 40


class InterpreterError(Exception):
    """El intérprete no pudo producir un resultado utilizable."""


class InvalidLlmOutput(InterpreterError):
    pass


@dataclass(frozen=True)
class ProposedAction:
    device: str
    action: str


@dataclass(frozen=True)
class LlmResult:
    mode: str
    speech: str
    actions: tuple[ProposedAction, ...]


def response_schema(catalog: DeviceCatalog) -> dict:
    """Esquema JSON para el parámetro `format` de Ollama."""
    action_keys = sorted({key for device in catalog.devices for key in device.actions})
    return {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": [PROPOSE, CLARIFY]},
            "speech": {"type": "string"},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "device": {
                            "type": "string",
                            "enum": [device.name for device in catalog.devices],
                        },
                        "action": {"type": "string", "enum": action_keys},
                    },
                    "required": ["device", "action"],
                },
            },
        },
        "required": ["mode", "speech", "actions"],
    }


def parse_llm_output(raw: str, catalog: DeviceCatalog) -> LlmResult:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise InvalidLlmOutput("la salida no es JSON") from error
    if not isinstance(data, dict):
        raise InvalidLlmOutput("la salida no es un objeto")

    mode = data.get("mode")
    if mode not in (PROPOSE, CLARIFY):
        raise InvalidLlmOutput(f"modo inválido: {mode!r}")
    speech = data.get("speech")
    if not isinstance(speech, str) or len(speech.split()) > MAX_SPEECH_WORDS:
        raise InvalidLlmOutput("speech inválido")
    speech = speech.strip()

    if mode == CLARIFY:
        if not speech:
            raise InvalidLlmOutput("clarify sin pregunta")
        return LlmResult(CLARIFY, speech, ())

    raw_actions = data.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise InvalidLlmOutput("propose sin acciones")
    chosen: dict[str, str] = {}
    for item in raw_actions:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("device"), str)
            or not isinstance(item.get("action"), str)
        ):
            raise InvalidLlmOutput("acción mal formada")
        try:
            catalog.resolve(item["device"], item["action"])
        except UnknownDeviceAction as error:
            raise InvalidLlmOutput(str(error)) from error
        if chosen.get(item["device"], item["action"]) != item["action"]:
            raise InvalidLlmOutput(f"acciones contradictorias sobre {item['device']}")
        chosen[item["device"]] = item["action"]
    return LlmResult(
        PROPOSE, speech, tuple(ProposedAction(d, a) for d, a in chosen.items())
    )
