"""Reproducción hacia el ESP32: cola de audio con prioridad, ritmo controlado y compuerta anti-eco."""

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from alivia_edge.config import VoiceConfig
from alivia_edge.interfaces import AudioOutput

logger = logging.getLogger(__name__)

BYTES_PER_SAMPLE = 2


@dataclass
class _Utterance:
    text: str
    priority: str
    utterance_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    cancelled: bool = False
    began: bool = False


class Playback:
    """Una frase a la vez. La emergencia pasa al frente y puede interrumpir la que suena."""

    def __init__(
        self,
        output: AudioOutput,
        speech,
        sample_rate: int,
        config: VoiceConfig,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._output = output
        self._speech = speech
        self._rate = sample_rate
        self._config = config
        self._clock = clock
        self._queue: deque[_Utterance] = deque()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._current: _Utterance | None = None
        self._done: dict[str, asyncio.Event] = {}
        self._gate_until = 0.0
        # Se llama (utterance_id) cuando una frase terminó de sonar; abre la ventana de confirmación.
        self.on_finished: Callable[[str], None] | None = None

    def start(self) -> None:
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)

    def is_gated(self) -> bool:
        """True mientras el micrófono oiría al propio parlante: no se procesa audio para activación ni comandos."""
        return (
            self._current is not None
            or bool(self._queue)
            or self._clock() < self._gate_until
        )

    def enqueue(self, text: str, priority: str = "normal") -> str:
        utterance = _Utterance(text, priority)
        if priority == "emergency":
            self._queue.appendleft(utterance)
        else:
            self._queue.append(utterance)
        self._wake.set()
        return utterance.utterance_id

    async def cancel_all(self) -> None:
        """Vacía la cola y corta lo que suena (audio_cancel)."""
        for pending in self._queue:
            pending.cancelled = True
        self._queue.clear()
        current = self._current
        if current is not None:
            current.cancelled = True
            if current.began:
                await self._output.send_json(
                    {"type": "audio_cancel", "utteranceId": current.utterance_id}
                )
            done = self._done.get(current.utterance_id)
            if done:
                done.set()
        self._gate_until = self._clock() + self._config.echo_tail_ms / 1000

    def on_playback_done(self, utterance_id: str) -> None:
        done = self._done.get(utterance_id)
        if done:
            done.set()

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            while self._queue:
                utterance = self._queue.popleft()
                self._current = utterance
                try:
                    await self._play(utterance)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("fallo reproduciendo %r", utterance.text)
                finally:
                    self._current = None
                    self._gate_until = self._clock() + self._config.echo_tail_ms / 1000
            self._wake.clear()

    async def _play(self, utterance: _Utterance) -> None:
        pcm = await self._speech.get(utterance.text, self._rate)
        if utterance.cancelled:
            return
        cfg = self._config
        done = self._done[utterance.utterance_id] = asyncio.Event()
        try:
            await self._output.send_json(
                {
                    "type": "audio_begin",
                    "utteranceId": utterance.utterance_id,
                    "sampleRate": self._rate,
                    "priority": utterance.priority,
                }
            )
            utterance.began = True
            started = self._clock()
            chunk_bytes = self._rate * BYTES_PER_SAMPLE * cfg.playback_chunk_ms // 1000
            lead_s = cfg.playback_lead_ms / 1000
            sent_s = 0.0
            for offset in range(0, len(pcm), chunk_bytes):
                # Prefill de `lead_s` y después ritmo de tiempo real: el jitter buffer del ESP32 no se desborda.
                while (
                    sent_s - (self._clock() - started) > lead_s
                    and not utterance.cancelled
                ):
                    await asyncio.sleep(cfg.playback_chunk_ms / 2000)
                if utterance.cancelled:
                    return
                chunk = pcm[offset : offset + chunk_bytes]
                await self._output.send_bytes(chunk)
                sent_s += len(chunk) / (self._rate * BYTES_PER_SAMPLE)
            await self._output.send_json(
                {"type": "audio_end", "utteranceId": utterance.utterance_id}
            )
            timeout = (
                max(0.0, sent_s - (self._clock() - started))
                + cfg.playback_done_margin_s
            )
            try:
                await asyncio.wait_for(done.wait(), timeout)
            except TimeoutError:
                logger.warning(
                    "playback_done no llegó para %s; se asume terminado",
                    utterance.utterance_id,
                )
        finally:
            self._done.pop(utterance.utterance_id, None)
        if not utterance.cancelled and self.on_finished:
            self._gate_until = self._clock() + cfg.echo_tail_ms / 1000
            self.on_finished(utterance.utterance_id)
