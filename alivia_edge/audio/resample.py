"""Remuestreo de PCM int16 mono (Piper genera a 22050 Hz; el ESP32 anuncia su propia tasa)."""

import numpy as np

FIR_TAPS = 101
# Fracción de la tasa destino; deja banda de transición bajo su Nyquist.
CUTOFF_MARGIN = 0.45


def resample_pcm16(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    """Filtro paso bajo (si se reduce la tasa, para no generar aliasing) e interpolación lineal."""
    if source_rate == target_rate or not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if target_rate < source_rate:
        # Frecuencia de corte en ciclos por muestra de origen.
        cutoff = CUTOFF_MARGIN * target_rate / source_rate
        taps = np.arange(FIR_TAPS) - (FIR_TAPS - 1) / 2
        kernel = 2 * cutoff * np.sinc(2 * cutoff * taps) * np.hamming(FIR_TAPS)
        samples = np.convolve(samples, kernel / kernel.sum(), mode="same")
    positions = (
        np.arange(int(len(samples) * target_rate / source_rate))
        * source_rate
        / target_rate
    )
    resampled = np.interp(positions, np.arange(len(samples)), samples)
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()
