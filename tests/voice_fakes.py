"""Fakes para probar el pipeline de voz sin modelos ni GPU.

El "audio" de las pruebas lleva el texto dentro: una frase es texto relleno hasta completar frames de VAD y el
silencio son frames de ceros. Así el reconocedor, el VAD y el transcriptor falsos se comportan como los reales
(final de frase tras silencio, [unk] fuera de gramática) sin procesar audio de verdad.
"""

import asyncio
import functools
import json
from dataclasses import replace

from alivia_edge.config import VoiceConfig
from alivia_edge.devices.catalog import DeviceCatalog, DeviceStates
from alivia_edge.emergency.detector import EmergencyDetector
from alivia_edge.emergency.notifier import NotifyResult
from alivia_edge.interfaces import RecognitionEvent, Transcript
from alivia_edge.mqtt.bus import ActuatorResult
from alivia_edge.nlu.contract import InterpreterError, LlmResult, ProposedAction
from alivia_edge.session import Session, SessionDeps
from alivia_edge.text import normalize
from alivia_edge.transport.protocol import Hello

FRAME_SAMPLES = 160
FRAME_BYTES = FRAME_SAMPLES * 2


def make_config(**overrides) -> VoiceConfig:
    base = {
        "ws_token": "secret",
        "vad_end_ms": 30,
        "preroll_ms": 10,
        "no_speech_timeout_s": 0.3,
        "confirm_window_s": 0.4,
        "echo_tail_ms": 0,
        "playback_done_margin_s": 0.3,
        "playback_chunk_ms": 20,
        "emergency_cancel_window_s": 5.0,
        "emergency_dedupe_s": 10.0,
        "actuator_timeout_s": 0.3,
    }
    return replace(VoiceConfig(), **{**base, **overrides})


def speech(text: str) -> bytes:
    raw = text.encode()
    raw += b" " * (-len(raw) % FRAME_BYTES)
    return raw


def silence(frames: int = 4) -> bytes:
    return bytes(FRAME_BYTES * frames)


class FakeVad:
    frame_samples = FRAME_SAMPLES

    def is_speech(self, frame: bytes) -> bool:
        return any(frame)

    def reset(self) -> None:
        pass


def decode(pcm: bytes) -> str:
    return pcm.replace(b"\x00", b"").decode().strip()


class FakeRecognizer:
    """Como Vosk con gramática: lo que no está en ella sale como [unk]; emite el final tras el silencio."""

    def __init__(self, grammar: list[str]):
        self._phrases = sorted(
            (normalize(g).split() for g in grammar if g != "[unk]"),
            key=len,
            reverse=True,
        )
        self._heard = ""

    def reset(self) -> None:
        self._heard = ""

    def _match(self, text: str) -> str:
        words, out, i = normalize(text).split(), [], 0
        while i < len(words):
            for phrase in self._phrases:
                if words[i : i + len(phrase)] == phrase:
                    out += phrase
                    i += len(phrase)
                    break
            else:
                out.append("[unk]")
                i += 1
        return " ".join(out)

    def accept(self, pcm: bytes) -> list[RecognitionEvent]:
        if any(pcm):
            self._heard = f"{self._heard} {decode(pcm)}".strip()
            matched = self._match(self._heard)
            return (
                [RecognitionEvent(matched, False)]
                if matched.replace("[unk]", "").strip()
                else []
            )
        if self._heard:
            text, self._heard = self._match(self._heard), ""
            return [RecognitionEvent(text, True)]
        return []


class FakeTranscriber:
    def __init__(self):
        self.calls: list[str] = []

    def transcribe(self, pcm: bytes) -> Transcript:
        text = decode(pcm)
        self.calls.append(text)
        return Transcript(text) if text else Transcript("", 1.0, -9.0)


class FakeInterpreter:
    def __init__(self, rules: dict[str, LlmResult | Exception]):
        self.rules = {normalize(key): value for key, value in rules.items()}
        self.calls: list[tuple[str, tuple[ProposedAction, ...], str]] = []

    def interpret(self, text, states, pending=(), earlier_request=""):
        self.calls.append((text, tuple(pending), earlier_request))
        outcome = self.rules.get(normalize(text), InterpreterError("sin regla"))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def propose(*pairs: tuple[str, str], speech_text: str = "") -> LlmResult:
    return LlmResult(
        "propose", speech_text, tuple(ProposedAction(d, a) for d, a in pairs)
    )


def clarify(question: str) -> LlmResult:
    return LlmResult("clarify", question, ())


class FakeSpeech:
    """Registra lo que Piper diría; devuelve 100 ms de audio por frase."""

    def __init__(self):
        self.spoken: list[str] = []

    async def get(self, text: str, rate: int) -> bytes:
        self.spoken.append(text)
        return bytes(rate * 2 // 10)

    async def warm(self, phrases, rate) -> None:
        pass


class FakeBus:
    def __init__(self, status: str = "ok", confirmed: dict[str, str] | None = None):
        self.status = status
        self.confirmed = confirmed or {
            "puerta": "OPEN",
            "luz_cuarto": "ON",
            "ventana": "OPEN",
        }
        self.calls: list[tuple[str, str, str]] = []

    async def execute(self, *, source_device_id, spec, action):
        self.calls.append((source_device_id, spec.device_id, action.api_action))
        if self.status == "timeout":
            await asyncio.sleep(0.01)
        return ActuatorResult(
            "cmd",
            self.status,
            self.confirmed.get(spec.name),
            None if self.status == "ok" else "X",
        )


class FakeNotifier:
    """Sustituye al notificador HTTP: registra avisos y cancelaciones."""

    def __init__(self, delivered: bool = True):
        self.delivered = delivered
        self.notified: list[tuple[str, str]] = []
        self.cancelled: list[str] = []

    async def notify(self, device_id, trigger_text, on_registered=None):
        self.notified.append((device_id, trigger_text))
        emergency_id = f"em-{len(self.notified)}"
        if on_registered:
            on_registered(emergency_id)
        return NotifyResult(emergency_id, self.delivered)

    async def cancel(self, emergency_id):
        self.cancelled.append(emergency_id)


class FakeOutput:
    """El ESP32 visto desde el edge: guarda lo recibido y responde playback_done cuando termina de 'sonar'."""

    def __init__(self, auto_done: bool = True):
        self.messages: list[dict] = []
        self.audio_chunks = 0
        self.auto_done = auto_done
        self.session: Session | None = None

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)
        if message["type"] == "audio_end" and self.auto_done:
            asyncio.get_running_loop().call_later(
                0.01,
                self.session.on_json,
                {"type": "playback_done", "utteranceId": message["utteranceId"]},
            )

    async def send_bytes(self, data: bytes) -> None:
        self.audio_chunks += 1

    def types(self) -> list[str]:
        return [m["type"] for m in self.messages]


class Harness:
    """Una sesión completa con todos los componentes falsos."""

    def __init__(
        self, rules=None, bus=None, notifier=None, auto_done=True, config=None
    ):
        from alivia_edge.asr.grammar import emergency_grammar, wake_grammar

        self.config = config or make_config()
        self.catalog = DeviceCatalog()
        self.transcriber = FakeTranscriber()
        self.interpreter = FakeInterpreter(rules or {})
        self.speech = FakeSpeech()
        self.bus = bus or FakeBus()
        self.notifier = notifier or FakeNotifier()
        self.output = FakeOutput(auto_done)
        cfg = self.config
        self.deps = deps = SessionDeps(
            config=cfg,
            catalog=self.catalog,
            states=DeviceStates(self.catalog),
            transcriber=self.transcriber,
            interpreter=self.interpreter,
            speech=self.speech,
            bus=self.bus,
            notifier=self.notifier,
            detector=EmergencyDetector(
                cfg.wake_phrases, cfg.emergency_words, cfg.cancel_phrases
            ),
            wake_recognizer=lambda: FakeRecognizer(wake_grammar(cfg)),
            emergency_recognizer=lambda: FakeRecognizer(emergency_grammar(cfg)),
            vad=FakeVad,
        )
        self.session = Session(
            Hello("esp32-test", ("microphone", "speaker"), 16000, 320),
            self.output,
            deps,
        )
        self.output.session = self.session

    async def __aenter__(self):
        await self.session.start()
        return self

    async def __aexit__(self, *exc):
        await self.session.close()

    async def say(self, text: str, tail: int = 4) -> None:
        """La persona dice `text` y calla: el audio entra en frames de 20 ms como llegaría por el WebSocket."""
        data = speech(text)
        for offset in range(0, len(data), FRAME_BYTES):
            await self.session.on_audio(data[offset : offset + FRAME_BYTES])
        for _ in range(tail):
            await self.session.on_audio(silence(1))

    async def listening(self) -> None:
        """Espera a que termine de sonar la pregunta y se abra la ventana de confirmación."""
        await until(lambda: self.session.snapshot()["window"])

    async def idle(self) -> None:
        await until(
            lambda: (
                self.session.state.value == "IDLE"
                and not self.session.snapshot()["speaking"]
            )
        )


async def until(condition, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("la condición no se cumplió a tiempo")
        await asyncio.sleep(0.005)


def to_json(data) -> str:
    return json.dumps(data)


def aio(function):
    """Ejecuta una prueba asíncrona sin depender de plugins de pytest."""

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper
