"""Normalización de texto en español para comparar frases sin depender de tildes ni signos."""

import re
import unicodedata
from collections.abc import Iterable

from rapidfuzz import fuzz

WAKE_FILLERS = frozenset({"oye", "ey", "hey", "oiga", "ok"})
WAKE_FUZZY_THRESHOLD = 80


def normalize(text: str) -> str:
    """Minúsculas, sin tildes ni signos, con espacios simples."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def wake_keywords(wake_phrases: Iterable[str]) -> frozenset[str]:
    """Última palabra de cada frase de activación ("oye alivia" -> "alivia")."""
    return frozenset(tokens(phrase)[-1] for phrase in wake_phrases if tokens(phrase))


def is_wake_token(token: str, keywords: Iterable[str]) -> bool:
    """Coincidencia difusa: Whisper a veces escribe "olivia" por "alivia"."""
    return any(
        fuzz.ratio(token, keyword) >= WAKE_FUZZY_THRESHOLD for keyword in keywords
    )


def strip_wake(text: str, keywords: Iterable[str]) -> str:
    """Quita la palabra de activación (y sus muletillas) del inicio del texto."""
    keywords = tuple(keywords)
    words = tokens(text)
    start = 0
    while start < len(words) and (
        words[start] in WAKE_FILLERS or is_wake_token(words[start], keywords)
    ):
        start += 1
    return " ".join(words[start:])
