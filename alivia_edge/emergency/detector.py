"""Detección de emergencia por texto. Pura, sin LLM ni modelos: se prueba con cadenas."""

from collections.abc import Iterable

from alivia_edge.text import (
    WAKE_FILLERS,
    is_wake_token,
    normalize,
    tokens,
    wake_keywords,
)

POLITE_FILLERS = frozenset({"por", "favor"})


class EmergencyDetector:
    def __init__(
        self,
        wake_phrases: Iterable[str],
        emergency_words: Iterable[str],
        cancel_phrases: Iterable[str],
    ):
        self._wake_keywords = wake_keywords(wake_phrases)
        self._emergency_words = frozenset(normalize(word) for word in emergency_words)
        self._cancel_phrases = tuple(normalize(phrase) for phrase in cancel_phrases)

    def contains(self, text: str) -> bool:
        """Palabra de activación seguida de una palabra de emergencia en la misma frase."""
        words = tokens(text)
        return any(
            is_wake_token(words[i], self._wake_keywords)
            and words[i + 1] in self._emergency_words
            for i in range(len(words) - 1)
        )

    def is_only(self, text: str) -> bool:
        """El texto, sin palabra de activación ni cortesías, son solo palabras de emergencia.

        "ayuda" y "oye alivia ayuda" cuentan; "ayúdame a abrir la puerta" no.
        """
        rest = [
            word
            for word in tokens(text)
            if word not in WAKE_FILLERS
            and word not in POLITE_FILLERS
            and not is_wake_token(word, self._wake_keywords)
        ]
        return bool(rest) and all(word in self._emergency_words for word in rest)

    def is_emergency(self, text: str) -> bool:
        return self.contains(text) or self.is_only(text)

    def is_cancel(self, text: str) -> bool:
        padded = f" {normalize(text)} "
        return any(f" {phrase} " in padded for phrase in self._cancel_phrases)
