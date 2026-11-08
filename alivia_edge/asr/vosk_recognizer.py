"""Reconocedor Vosk con gramática restringida. `vosk` se importa al cargar el modelo, no al importar el módulo."""

import json

from alivia_edge.interfaces import RecognitionEvent


class VoskModel:
    """Modelo compartido por todas las sesiones; cada sesión crea sus propios reconocedores."""

    def __init__(self, model_path: str, sample_rate: int = 16000):
        from vosk import Model, SetLogLevel

        SetLogLevel(-1)
        self._model = Model(model_path)
        self._sample_rate = sample_rate

    def recognizer(self, grammar: list[str]) -> "VoskRecognizer":
        from vosk import KaldiRecognizer

        return VoskRecognizer(
            KaldiRecognizer(self._model, self._sample_rate, json.dumps(grammar))
        )


class VoskRecognizer:
    def __init__(self, kaldi):
        self._kaldi = kaldi

    def accept(self, pcm: bytes) -> list[RecognitionEvent]:
        if self._kaldi.AcceptWaveform(pcm):
            text = json.loads(self._kaldi.Result()).get("text", "")
            return [RecognitionEvent(text, True)]
        partial = json.loads(self._kaldi.PartialResult()).get("partial", "")
        return [RecognitionEvent(partial, False)] if partial else []

    def reset(self) -> None:
        self._kaldi.Reset()
