"""Síntesis con Piper. `piper-tts` se importa al cargar la voz."""


class PiperSynthesizer:
    def __init__(self, voice_path: str):
        from piper import PiperVoice

        self._voice = PiperVoice.load(voice_path)
        self.sample_rate = self._voice.config.sample_rate

    def synthesize(self, text: str) -> bytes:
        """PCM int16 mono a `sample_rate`, sin MP3 ni cabecera WAV."""
        return b"".join(
            chunk.audio_int16_bytes for chunk in self._voice.synthesize(text)
        )
