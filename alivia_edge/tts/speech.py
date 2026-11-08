"""Frases fijas y caché de audio. Piper corre en un executor y cada frase se sintetiza una sola vez por tasa."""

import asyncio
import logging

from alivia_edge.audio.resample import resample_pcm16
from alivia_edge.devices.catalog import DeviceCatalog
from alivia_edge.interfaces import Synthesizer
from alivia_edge.logs import stage

logger = logging.getLogger(__name__)

# Ninguna frase puede contener "alivia" seguida de una palabra de emergencia (hay un test que lo revisa).
PHRASES = {
    "emergency_started": "Pedí ayuda",
    "emergency_sent": "Tu aviso fue enviado",
    "emergency_failed": "No pude enviar el aviso, sigo intentando",
    "emergency_cancelled": "Marqué el aviso como falsa alarma",
    "not_understood": "No te entendí bien, ¿puedes repetirlo?",
    "no_response": "No te escuché, cancelé la acción",
    "cancelled": "Listo, no hice nada",
    "gave_up": "No pude entenderte, cancelé la acción",
}


def all_fixed_phrases(catalog: DeviceCatalog) -> list[str]:
    return [*PHRASES.values(), *catalog.all_phrases()]


class SpeechLibrary:
    def __init__(self, synthesizer: Synthesizer):
        self._synthesizer = synthesizer
        self._cache: dict[tuple[str, int], bytes] = {}

    async def get(self, text: str, target_rate: int) -> bytes:
        key = (text, target_rate)
        if key not in self._cache:
            self._cache[key] = await asyncio.get_running_loop().run_in_executor(
                None, self._render, text, target_rate
            )
        return self._cache[key]

    def _render(self, text: str, target_rate: int) -> bytes:
        with stage("piper"):
            pcm = self._synthesizer.synthesize(text)
        return resample_pcm16(pcm, self._synthesizer.sample_rate, target_rate)

    async def warm(self, phrases: list[str], target_rate: int) -> None:
        """Precalienta la caché; las frases de emergencia van primero."""
        for phrase in phrases:
            await self.get(phrase, target_rate)
