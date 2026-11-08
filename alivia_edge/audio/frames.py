"""Captura de un enunciado: re-trocea el PCM, aplica VAD y decide cuándo terminó la frase."""

from collections import deque

from alivia_edge.interfaces import VoiceActivityDetector

BYTES_PER_SAMPLE = 2
SAMPLE_RATE = 16000


class Capture:
    """Acumula audio desde el primer instante de voz hasta `end_ms` de silencio.

    Conserva un pre-roll corto para no cortar el inicio de la primera palabra.
    """

    def __init__(
        self, vad: VoiceActivityDetector, end_ms: int, preroll_ms: int, max_s: float
    ):
        self._vad = vad
        self._frame_bytes = vad.frame_samples * BYTES_PER_SAMPLE
        self._frame_ms = vad.frame_samples * 1000 / SAMPLE_RATE
        self._end_ms = end_ms
        self._max_bytes = int(max_s * SAMPLE_RATE * BYTES_PER_SAMPLE)
        self._preroll: deque[bytes] = deque(
            maxlen=max(1, int(preroll_ms / self._frame_ms))
        )
        self._pending = b""
        self._audio = bytearray()
        self._silence_ms = 0.0
        self.speech_started = False
        self.finished = False
        vad.reset()

    def feed(self, pcm: bytes) -> None:
        self._pending += pcm
        while len(self._pending) >= self._frame_bytes and not self.finished:
            frame, self._pending = (
                self._pending[: self._frame_bytes],
                self._pending[self._frame_bytes :],
            )
            self._process(frame)

    def _process(self, frame: bytes) -> None:
        speech = self._vad.is_speech(frame)
        if not self.speech_started:
            if not speech:
                self._preroll.append(frame)
                return
            self.speech_started = True
            self._audio.extend(b"".join(self._preroll))
        self._audio.extend(frame)
        self._silence_ms = 0.0 if speech else self._silence_ms + self._frame_ms
        if self._silence_ms >= self._end_ms or len(self._audio) >= self._max_bytes:
            self.finished = True

    @property
    def audio(self) -> bytes:
        return bytes(self._audio)
