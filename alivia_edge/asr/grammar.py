"""Gramáticas restringidas de Vosk, configurables."""

from alivia_edge.config import VoiceConfig
from alivia_edge.text import normalize

UNKNOWN = "[unk]"


def wake_grammar(config: VoiceConfig) -> list[str]:
    """Solo palabras de activación; el resto se reconoce como [unk]."""
    return [*(normalize(phrase) for phrase in config.wake_phrases), UNKNOWN]


def emergency_grammar(config: VoiceConfig) -> list[str]:
    """Solo emergencia: combinaciones activación x emergencia y las frases de cancelación.

    No incluye "ayuda" suelta, para que el eco del propio "Pedí ayuda" no la dispare.
    """
    combos = [
        f"{normalize(wake)} {normalize(word)}"
        for wake in config.wake_phrases
        for word in config.emergency_words
    ]
    return [*combos, *(normalize(phrase) for phrase in config.cancel_phrases), UNKNOWN]
