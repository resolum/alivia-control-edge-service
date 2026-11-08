import pytest

from alivia_edge.devices.catalog import DeviceCatalog
from alivia_edge.emergency.detector import EmergencyDetector
from alivia_edge.replies import classify_reply, join_es
from alivia_edge.text import normalize, strip_wake, wake_keywords
from alivia_edge.tts.speech import all_fixed_phrases

KEYWORDS = wake_keywords(("alivia", "oye alivia"))
DETECTOR = EmergencyDetector(
    ("alivia", "oye alivia", "ey alivia"),
    ("ayuda", "auxilio"),
    ("cancela", "falsa alarma", "estoy bien"),
)


def test_normalize_drops_accents_and_punctuation():
    assert normalize("¡Oye, ALIVIA! ¿Abre la puerta?") == "oye alivia abre la puerta"


@pytest.mark.parametrize(
    "text,rest",
    [
        ("Oye Alivia, abre la puerta", "abre la puerta"),
        ("alivia abre la puerta", "abre la puerta"),
        ("oye olivia abre la puerta", "abre la puerta"),  # Whisper confunde la vocal
        ("abre la puerta", "abre la puerta"),
        ("ey alivia", ""),
    ],
)
def test_strip_wake(text, rest):
    assert strip_wake(text, KEYWORDS) == rest


@pytest.mark.parametrize(
    "text,kind",
    [
        ("sí", "yes"),
        ("Dale", "yes"),
        ("ok", "yes"),
        ("confirmo", "yes"),
        ("sí, por favor", "yes"),
        ("no", "no"),
        ("cancela", "no"),
        ("déjalo", "no"),
        ("no, déjalo", "no"),
        ("sí, pero la puerta no", "other"),
        ("solo la luz", "other"),
        ("sí no", "other"),
        ("", "other"),
    ],
)
def test_classify_reply(text, kind):
    assert classify_reply(text) == kind


def test_join_es():
    assert join_es(["a"]) == "a"
    assert join_es(["a", "b"]) == "a y b"
    assert join_es(["a", "b", "c"]) == "a, b y c"


@pytest.mark.parametrize(
    "text",
    ["oye alivia ayuda", "Ey Alivia, auxilio", "alivia ayuda", "oye olivia ayuda"],
)
def test_emergency_phrase_in_one_go(text):
    assert DETECTOR.contains(text)


@pytest.mark.parametrize(
    "text",
    ["ayuda", "auxilio", "oye alivia ayuda", "ayuda por favor", "auxilio auxilio"],
)
def test_emergency_word_alone(text):
    assert DETECTOR.is_only(text)


@pytest.mark.parametrize(
    "text",
    [
        "ayúdame a abrir la puerta",
        "oye alivia ayúdame a abrir la puerta",
        "abre la puerta",
        "ayuda con la ventana",
        "alivia abre la puerta ayuda",
        "necesito ayuda",
    ],
)
def test_not_an_emergency(text):
    assert not DETECTOR.is_emergency(text)


def test_cancel_phrases():
    assert DETECTOR.is_cancel("Falsa alarma")
    assert DETECTOR.is_cancel("ya estoy bien, gracias")
    assert not DETECTOR.is_cancel("abre la puerta")


def test_no_spoken_phrase_can_trigger_an_emergency():
    """Piper nunca debe decir "alivia" + palabra de emergencia: sería un bucle de eco."""
    from alivia_edge.tts.speech import PHRASES

    phrases = [*PHRASES.values(), *all_fixed_phrases(DeviceCatalog())]
    for phrase in phrases:
        assert not DETECTOR.contains(phrase), phrase
        assert "alivia" not in normalize(phrase), phrase
