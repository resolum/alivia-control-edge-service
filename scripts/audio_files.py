"""Lectura y escritura de WAV PCM 16 kHz mono para las herramientas de prueba."""

import wave
from pathlib import Path

from alivia_edge.audio.resample import resample_pcm16


def read_wav_16k_mono(path: str) -> bytes:
    with wave.open(path, "rb") as wav:
        if wav.getsampwidth() != 2:
            raise SystemExit(f"{path}: se necesita PCM de 16 bits")
        pcm = wav.readframes(wav.getnframes())
        channels, rate = wav.getnchannels(), wav.getframerate()
    if channels == 2:  # se toma el canal izquierdo
        pcm = b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 4))
    return resample_pcm16(pcm, rate, 16000)


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
