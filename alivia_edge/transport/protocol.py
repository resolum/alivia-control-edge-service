"""Mensajes del protocolo WebSocket (ver docs/protocolo-websocket.md)."""

import hmac
from dataclasses import dataclass

from alivia_edge.config import VoiceConfig

MIC_SAMPLE_RATE = 16000


class HelloRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Hello:
    device_id: str
    capabilities: tuple[str, ...]
    playback_sample_rate: int
    frame_samples: int


def parse_hello(message: object, config: VoiceConfig) -> Hello:
    """Valida el hello del ESP32. Lanza HelloRejected con la razón que se devuelve en `error`."""
    if not isinstance(message, dict) or message.get("type") != "hello":
        raise HelloRejected("bad_hello")
    device_id = message.get("deviceId")
    capabilities = message.get("capabilities")
    token = message.get("token")
    if (
        not isinstance(device_id, str)
        or not device_id
        or not isinstance(capabilities, list)
    ):
        raise HelloRejected("bad_hello")
    if (
        not config.ws_token
        or not isinstance(token, str)
        or not hmac.compare_digest(token, config.ws_token)
    ):
        raise HelloRejected("unauthorized")
    playback_rate = message.get("playbackSampleRate", MIC_SAMPLE_RATE)
    frame_samples = message.get("frameSamples", 320)
    if (
        message.get("micSampleRate") != MIC_SAMPLE_RATE
        or message.get("bits") != 16
        or message.get("channels") != 1
        or not isinstance(playback_rate, int)
        or not 8000 <= playback_rate <= 48000
        or not isinstance(frame_samples, int)
        or frame_samples <= 0
    ):
        raise HelloRejected("unsupported_format")
    return Hello(
        device_id,
        tuple(str(item) for item in capabilities),
        playback_rate,
        frame_samples,
    )
