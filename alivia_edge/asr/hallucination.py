"""Descarta alucinaciones típicas de Whisper (frases basura, vacío, no_speech_prob alto)."""

from alivia_edge.interfaces import Transcript
from alivia_edge.text import normalize, tokens

KNOWN_JUNK = (
    "gracias por ver el video",
    "gracias por ver",
    "subtitulos realizados por la comunidad de amara org",
    "subtitulos por la comunidad de amara org",
    "suscribete al canal",
    "suscribete",
    "no olvides suscribirte",
    "hasta la proxima",
    "musica",
    "aplausos",
    "gracias",
)
MIN_LOGPROB = -1.0


def is_hallucination(transcript: Transcript, no_speech_prob_max: float) -> bool:
    text = normalize(transcript.text)
    if not text:
        return True
    if text in KNOWN_JUNK or any(
        text.startswith(junk) for junk in KNOWN_JUNK if len(junk) > 12
    ):
        return True
    if (
        transcript.no_speech_prob > no_speech_prob_max
        and transcript.avg_logprob < MIN_LOGPROB
    ):
        return True
    words = tokens(text)
    # Bucles de repetición ("sí sí sí sí sí sí ...") típicos de Whisper sobre ruido.
    return len(words) >= 6 and len(set(words)) <= 2
