"""Contratos de los componentes pesados. Los módulos reales los implementan con imports perezosos; los tests usan fakes."""

from dataclasses import dataclass
from typing import Protocol

from alivia_edge.nlu.contract import LlmResult, ProposedAction


@dataclass(frozen=True)
class RecognitionEvent:
    text: str
    final: bool


@dataclass(frozen=True)
class Transcript:
    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0


class StreamRecognizer(Protocol):
    """Reconocedor en streaming con gramática restringida (Vosk)."""

    def accept(self, pcm: bytes) -> list[RecognitionEvent]: ...

    def reset(self) -> None: ...


class VoiceActivityDetector(Protocol):
    frame_samples: int

    def is_speech(self, frame: bytes) -> bool: ...

    def reset(self) -> None: ...


class Transcriber(Protocol):
    def transcribe(self, pcm: bytes) -> Transcript: ...


class Interpreter(Protocol):
    def interpret(
        self,
        text: str,
        states: dict[str, str],
        pending: tuple[ProposedAction, ...] = (),
        earlier_request: str = "",
    ) -> LlmResult: ...


class Synthesizer(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> bytes:
        """PCM int16 mono a `sample_rate`."""


class AudioOutput(Protocol):
    """Salida hacia el ESP32 (el WebSocket de la sesión)."""

    async def send_json(self, message: dict) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...
