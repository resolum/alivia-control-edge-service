"""Transcripción con faster-whisper. El modelo se carga una sola vez; la inferencia corre en un executor."""

import logging

from alivia_edge.interfaces import Transcript
from alivia_edge.logs import stage

logger = logging.getLogger(__name__)

INITIAL_PROMPT = (
    "Órdenes para una casa: abre la puerta, cierra la puerta, abre la ventana, cierra la ventana, "
    "enciende la luz del cuarto, apaga la luz. Alivia. Sí, no, cancela."
)


class FasterWhisperTranscriber:
    def __init__(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        initial_prompt: str = INITIAL_PROMPT,
    ):
        import numpy as np
        from faster_whisper import WhisperModel

        self._np = np
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self._initial_prompt = initial_prompt

    def transcribe(self, pcm: bytes) -> Transcript:
        audio = (
            self._np.frombuffer(pcm, dtype=self._np.int16).astype(self._np.float32)
            / 32768.0
        )
        with stage("whisper"):
            segments, _ = self._model.transcribe(
                audio,
                language="es",
                beam_size=5,
                temperature=0,
                condition_on_previous_text=False,
                initial_prompt=self._initial_prompt,
            )
            parts = list(segments)  # el generador hace el trabajo aquí
        if not parts:
            return Transcript("", 1.0, -10.0)
        text = " ".join(part.text.strip() for part in parts).strip()
        return Transcript(
            text,
            no_speech_prob=max(part.no_speech_prob for part in parts),
            avg_logprob=sum(part.avg_logprob for part in parts) / len(parts),
        )
