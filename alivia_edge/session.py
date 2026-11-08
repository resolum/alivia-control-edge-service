"""Sesión de voz de un ESP32: palabra de activación, comando, confirmación, ejecución y emergencia.

La regla central vive aquí, en código: ninguna acción llega a MQTT sin una confirmación explícita
de la persona (y nunca por silencio). La emergencia es la única excepción y nunca toca MQTT.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import partial

from alivia_edge.asr.hallucination import is_hallucination
from alivia_edge.audio.frames import Capture
from alivia_edge.config import VoiceConfig
from alivia_edge.devices.catalog import DeviceCatalog, DeviceStates
from alivia_edge.emergency.detector import EmergencyDetector
from alivia_edge.emergency.notifier import EmergencyNotifier
from alivia_edge.interfaces import (
    AudioOutput,
    Interpreter,
    StreamRecognizer,
    Transcriber,
    VoiceActivityDetector,
)
from alivia_edge.mqtt.bus import ActuatorBus, ActuatorResult
from alivia_edge.nlu.contract import CLARIFY, PROPOSE, InterpreterError, ProposedAction
from alivia_edge.replies import classify_reply, join_es
from alivia_edge.state_machine import State, StateMachine
from alivia_edge.text import is_wake_token, strip_wake, tokens, wake_keywords
from alivia_edge.transport.playback import Playback
from alivia_edge.transport.protocol import Hello
from alivia_edge.tts.speech import PHRASES, all_fixed_phrases

logger = logging.getLogger(__name__)

MAX_UTTERANCE_BYTES = 15 * 16000 * 2


@dataclass
class SessionDeps:
    config: VoiceConfig
    catalog: DeviceCatalog
    states: DeviceStates
    transcriber: Transcriber
    interpreter: Interpreter
    speech: object  # SpeechLibrary: get(text, rate) y warm(phrases, rate)
    bus: ActuatorBus
    notifier: EmergencyNotifier
    detector: EmergencyDetector
    wake_recognizer: Callable[[], StreamRecognizer]
    emergency_recognizer: Callable[[], StreamRecognizer]
    vad: Callable[[], VoiceActivityDetector]
    clock: Callable[[], float] = time.monotonic


@dataclass
class Pending:
    kind: str  # "confirm" (acciones por confirmar) | "clarify" (pregunta abierta)
    actions: tuple[ProposedAction, ...]
    original: str
    question: str = ""
    rounds: int = 0


class Session:
    def __init__(self, hello: Hello, output: AudioOutput, deps: SessionDeps):
        self.device_id = hello.device_id
        self._deps = deps
        self._cfg = deps.config
        self._clock = deps.clock
        self._machine = StateMachine(deps.clock)
        self._playback = Playback(
            output, deps.speech, hello.playback_sample_rate, deps.config, deps.clock
        )
        self._playback.on_finished = self._on_utterance_finished
        self._wake = deps.wake_recognizer()
        self._emergency = deps.emergency_recognizer()
        self._vad = deps.vad()
        self._rate = hello.playback_sample_rate
        self._keywords = wake_keywords(self._cfg.wake_phrases)
        self._wake_vocab = {
            word for phrase in self._cfg.wake_phrases for word in tokens(phrase)
        }

        self._utterance_audio = bytearray()
        self._capture: Capture | None = None
        self._capture_deadline = 0.0
        self._window_after: str | None = None
        self._window_open = False
        self._pending: Pending | None = None
        self._job: asyncio.Task | None = None
        self._was_gated = False

        self._last_emergency_at = float("-inf")
        self._emergency_id: str | None = None
        self._emergency_cancelled = False
        self._emergency_window_until = 0.0
        self._emergency_task: asyncio.Task | None = None
        self._warm_task: asyncio.Task | None = None
        self.telemetry: dict[str, dict] = {}

    # ------------------------------------------------------------------ ciclo de vida

    @property
    def state(self) -> State:
        return self._machine.state

    async def start(self) -> None:
        self._playback.start()
        self._warm_task = asyncio.create_task(self._warm_speech())

    async def close(self) -> None:
        """Desconexión: se descarta cualquier acción pendiente. El aviso de emergencia en curso sigue en el notificador."""
        for task in (self._job, self._warm_task):
            if task:
                task.cancel()
        self._pending = None
        self._capture = None
        self._machine.transition(State.IDLE, "desconexión")
        await self._playback.stop()

    def snapshot(self) -> dict:
        return {
            "deviceId": self.device_id,
            "state": self.state.value,
            "speaking": self._playback.is_gated(),
            "window": self._window_open,
        }

    async def _warm_speech(self) -> None:
        phrases = [
            PHRASES["emergency_started"],
            PHRASES["emergency_sent"],
            PHRASES["emergency_failed"],
        ]
        phrases += [
            p for p in all_fixed_phrases(self._deps.catalog) if p not in phrases
        ]
        try:
            await self._deps.speech.warm(phrases, self._rate)
        except Exception:
            logger.exception("no se pudo precalentar el audio")

    # ------------------------------------------------------------------ entrada

    def on_json(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "playback_done" and isinstance(message.get("utteranceId"), str):
            self._playback.on_playback_done(message["utteranceId"])
        elif kind in ("voice_activity", "audio_level"):
            self.telemetry[kind] = message

    async def on_audio(self, pcm: bytes) -> None:
        now = self._clock()
        await self._check_deadlines(now)

        # La emergencia escucha siempre: también durante la reproducción y mientras se procesa.
        for event in self._emergency.accept(pcm):
            if self._deps.detector.contains(event.text):
                await self.trigger_emergency(event.text)
                return
            if event.final and self._deps.detector.is_cancel(event.text):
                await self._cancel_emergency(now)

        if self._playback.is_gated():
            self._was_gated = True
            return
        if self._was_gated:
            self._wake.reset()
            self._utterance_audio.clear()
            self._was_gated = False

        state = self._machine.state
        if state is State.IDLE:
            self._listen_for_wake(pcm)
        elif self._capture is not None and (
            state is State.GRABANDO or self._window_open
        ):
            self._feed_capture(pcm)

    # ------------------------------------------------------------------ activación y captura

    def _listen_for_wake(self, pcm: bytes) -> None:
        self._utterance_audio.extend(pcm)
        del self._utterance_audio[:-MAX_UTTERANCE_BYTES]
        for event in self._wake.accept(pcm):
            if not event.final:
                continue
            audio = bytes(self._utterance_audio)
            self._utterance_audio.clear()
            words = tokens(event.text)
            if not any(is_wake_token(word, self._keywords) for word in words):
                continue
            if any(word not in self._wake_vocab for word in words):
                # "alivia abre la puerta" dicho de corrido: el enunciado completo va a Whisper.
                self._machine.transition(State.PROCESANDO, "comando en la misma frase")
                self._start_job(self._process_command(audio))
            else:
                self._capture = Capture(
                    self._vad,
                    self._cfg.vad_end_ms,
                    self._cfg.preroll_ms,
                    self._cfg.max_utterance_s,
                )
                self._capture_deadline = self._clock() + self._cfg.no_speech_timeout_s
                self._machine.transition(State.GRABANDO, "palabra de activación")
            return

    def _feed_capture(self, pcm: bytes) -> None:
        capture = self._capture
        capture.feed(pcm)
        if not capture.finished:
            return
        self._capture = None
        audio = capture.audio
        confirming = self._machine.state is State.ESPERANDO_CONFIRMACION
        self._window_open = False
        self._machine.transition(State.PROCESANDO, "fin de frase")
        self._start_job(
            self._process_confirmation(audio)
            if confirming
            else self._process_command(audio)
        )

    async def _check_deadlines(self, now: float) -> None:
        capture = self._capture
        if capture is None or capture.speech_started or now < self._capture_deadline:
            return
        if self._machine.state is State.GRABANDO:
            logger.info("nadie habló tras la palabra de activación")
            self._reset()
        elif self._machine.state is State.ESPERANDO_CONFIRMACION and self._window_open:
            logger.info("ventana de confirmación vencida: se cancela todo")
            self._reset()
            self._playback.enqueue(PHRASES["no_response"])

    def _on_utterance_finished(self, utterance_id: str) -> None:
        """La pregunta terminó de sonar: ahora corren los segundos de la ventana de confirmación."""
        if (
            self._machine.state is State.ESPERANDO_CONFIRMACION
            and utterance_id == self._window_after
        ):
            self._capture = Capture(
                self._vad,
                self._cfg.vad_end_ms,
                self._cfg.preroll_ms,
                self._cfg.max_utterance_s,
            )
            self._capture_deadline = self._clock() + self._cfg.confirm_window_s
            self._window_open = True

    # ------------------------------------------------------------------ comando

    def _start_job(self, work: Coroutine) -> None:
        self._job = asyncio.create_task(self._guarded(work))

    async def _guarded(self, work: Coroutine) -> None:
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("error procesando la orden; se cancela")
            self._reset()
            self._playback.enqueue(PHRASES["not_understood"])

    def _reset(self) -> None:
        self._pending = None
        self._capture = None
        self._window_open = False
        self._window_after = None
        self._machine.transition(State.IDLE, "reinicio")

    async def _run(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(None, function, *args)

    async def _transcribe(self, audio: bytes) -> str | None:
        transcript = await self._run(self._deps.transcriber.transcribe, audio)
        if is_hallucination(transcript, self._cfg.no_speech_prob_max):
            logger.info("transcripción descartada: %r", transcript.text)
            return None
        logger.info("transcripción: %r", transcript.text)
        return transcript.text

    async def _process_command(self, audio: bytes) -> None:
        text = await self._transcribe(audio)
        if text is None:
            self._reset()
            self._playback.enqueue(PHRASES["not_understood"])
            return
        if self._deps.detector.is_only(text):
            await self.trigger_emergency(text)
            return
        command = strip_wake(text, self._keywords)
        if not command:
            self._reset()
            return
        await self._interpret(command)

    async def _interpret(self, text: str, pending: Pending | None = None) -> None:
        actions = pending.actions if pending and pending.kind == "confirm" else ()
        earlier = ""
        if pending and pending.kind == "clarify":
            earlier = (
                f'pidió "{pending.original}" y tu pregunta fue "{pending.question}"'
            )
        try:
            result = await self._run(
                partial(
                    self._deps.interpreter.interpret,
                    text,
                    self._deps.states.snapshot(),
                    actions,
                    earlier,
                )
            )
        except InterpreterError as error:
            logger.warning("el intérprete falló: %s", error)
            self._reset()
            self._playback.enqueue(PHRASES["not_understood"])
            return
        rounds = pending.rounds + 1 if pending else 0
        if result.mode == PROPOSE:
            self._pending = Pending("confirm", result.actions, text, rounds=rounds)
            question = self._confirm_question(result.actions)
        elif result.mode == CLARIFY:
            self._pending = Pending(
                "clarify",
                (),
                pending.original if pending else text,
                result.speech,
                rounds,
            )
            question = result.speech
        else:  # pragma: no cover - parse_llm_output ya lo impide
            self._reset()
            return
        self._ask(question)

    def _confirm_question(self, actions: tuple[ProposedAction, ...]) -> str:
        phrases = [
            self._deps.catalog.resolve(a.device, a.action)[1].confirm for a in actions
        ]
        return f"¿Quieres que {join_es(phrases)}?"

    def _ask(self, question: str) -> None:
        self._machine.transition(State.ESPERANDO_CONFIRMACION, "pregunta")
        self._window_open = False
        self._capture = None
        self._window_after = self._playback.enqueue(question)

    # ------------------------------------------------------------------ confirmación

    async def _process_confirmation(self, audio: bytes) -> None:
        pending = self._pending
        text = await self._transcribe(audio)
        if pending is None:
            self._reset()
            return
        if text is None:
            await self._reask_or_give_up(pending)
            return
        if self._deps.detector.is_only(text):
            await self.trigger_emergency(text)
            return
        reply = classify_reply(text)
        if reply == "no":
            self._reset()
            self._playback.enqueue(PHRASES["cancelled"])
        elif reply == "yes" and pending.kind == "confirm":
            await self._execute(pending)
        elif pending.rounds >= self._cfg.max_reasks:
            self._give_up()
        else:
            await self._interpret(text, pending)

    async def _reask_or_give_up(self, pending: Pending) -> None:
        pending.rounds += 1
        if pending.rounds > self._cfg.max_reasks:
            self._give_up()
        else:
            self._ask(PHRASES["not_understood"])

    def _give_up(self) -> None:
        self._reset()
        self._playback.enqueue(PHRASES["gave_up"])

    # ------------------------------------------------------------------ ejecución

    async def _execute(self, pending: Pending) -> None:
        resolved = [
            self._deps.catalog.resolve(a.device, a.action) for a in pending.actions
        ]
        self._pending = None
        self._window_after = None
        self._machine.transition(State.EJECUTANDO, "confirmado")
        progress = [action.progress for _, action in resolved]
        progress[1:] = [text[0].lower() + text[1:] for text in progress[1:]]
        self._playback.enqueue(join_es(progress))

        results = await asyncio.gather(
            *(self._send(spec, action) for spec, action in resolved)
        )
        sentences = []
        for (spec, action), result in zip(resolved, results, strict=True):
            self._deps.states.update(
                spec.name, result.confirmed_state if result.status == "ok" else None
            )
            if result.status == "ok":
                sentences.append(f"Listo, {action.done}")
            elif result.status == "timeout":
                sentences.append(
                    f"No pude confirmar que se completó: {action.infinitive}"
                )
            else:
                sentences.append(f"No pude {action.infinitive}")
        self._playback.enqueue(". ".join(sentences))
        self._machine.transition(State.IDLE, "ejecución terminada")

    async def _send(self, spec, action) -> ActuatorResult:
        try:
            return await self._deps.bus.execute(
                source_device_id=self.device_id, spec=spec, action=action
            )
        except Exception:
            logger.exception("fallo enviando a %s", spec.name)
            return ActuatorResult("", "error", result_code="BUS_ERROR")

    # ------------------------------------------------------------------ emergencia

    async def trigger_emergency(self, trigger_text: str) -> None:
        """Prioridad máxima: interrumpe cualquier estado, cancela lo pendiente y avisa al cloud. Nunca usa MQTT."""
        now = self._clock()
        if now - self._last_emergency_at < self._cfg.emergency_dedupe_s:
            logger.info("emergencia repetida ignorada (anti-spam)")
            return
        self._last_emergency_at = now
        logger.warning("EMERGENCIA detectada: %r", trigger_text)
        if self._job is not None and self._job is not asyncio.current_task():
            self._job.cancel()
        self._reset()
        await self._playback.cancel_all()
        self._playback.enqueue(PHRASES["emergency_started"], priority="emergency")
        self._wake.reset()
        self._utterance_audio.clear()
        self._emergency_id = None
        self._emergency_cancelled = False
        self._emergency_window_until = now + self._cfg.emergency_cancel_window_s
        self._emergency_task = asyncio.create_task(self._notify_cloud(trigger_text))

    async def _notify_cloud(self, trigger_text: str) -> None:
        try:
            result = await self._deps.notifier.notify(
                self.device_id, trigger_text, self._register_emergency
            )
        except Exception:
            logger.exception(
                "fallo enviando la emergencia; queda en la cola persistente"
            )
            self._playback.enqueue(PHRASES["emergency_failed"], priority="emergency")
            return
        key = "emergency_sent" if result.delivered else "emergency_failed"
        self._playback.enqueue(PHRASES[key], priority="emergency")

    def _register_emergency(self, emergency_id: str) -> None:
        self._emergency_id = emergency_id

    async def _cancel_emergency(self, now: float) -> None:
        if (
            self._emergency_id is None
            or self._emergency_cancelled
            or now > self._emergency_window_until
        ):
            return
        self._emergency_cancelled = True
        await self._deps.notifier.cancel(self._emergency_id)
        self._playback.enqueue(PHRASES["emergency_cancelled"], priority="emergency")
