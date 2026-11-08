"""Clasificación por reglas de la respuesta a una confirmación. Sin LLM."""

from alivia_edge.text import tokens

YES_WORDS = frozenset(
    {
        "si",
        "dale",
        "ok",
        "okey",
        "confirmo",
        "claro",
        "vale",
        "adelante",
        "hazlo",
        "correcto",
    }
)
NO_WORDS = frozenset({"no", "cancela", "cancelar", "dejalo", "olvidalo", "negativo"})
FILLERS = frozenset({"por", "favor", "pues", "eh", "bueno", "gracias"})


def classify_reply(text: str) -> str:
    """ "yes", "no" u "other". Cualquier matiz ("sí, pero la puerta no") es "other" y se pasa al LLM."""
    words = [word for word in tokens(text) if word not in FILLERS]
    if not words:
        return "other"
    if all(word in YES_WORDS for word in words):
        return "yes"
    if all(word in NO_WORDS for word in words):
        return "no"
    return "other"


def join_es(items: list[str]) -> str:
    """["a", "b", "c"] -> "a, b y c"."""
    if len(items) <= 2:
        return " y ".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]
