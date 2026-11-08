import numpy as np

from alivia_edge.audio.resample import resample_pcm16


def tone(rate: int, hz: int, seconds: float = 0.5) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    return (np.sin(2 * np.pi * hz * t) * 12000).astype(np.int16).tobytes()


def dominant_hz(pcm: bytes, rate: int) -> float:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(float)
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.argmax(spectrum) * rate / len(samples))


def test_downsample_keeps_pitch_and_duration():
    out = resample_pcm16(tone(22050, 440), 22050, 16000)
    assert abs(len(out) / 2 - 8000) <= 2
    assert abs(dominant_hz(out, 16000) - 440) < 5


def test_upsample_and_same_rate():
    assert len(resample_pcm16(tone(16000, 300), 16000, 24000)) // 2 == 12000
    pcm = tone(16000, 300)
    assert resample_pcm16(pcm, 16000, 16000) is pcm


def test_frequencies_above_nyquist_are_filtered():
    out = resample_pcm16(tone(22050, 10000), 22050, 16000)  # 10 kHz no cabe en 16 kHz
    assert np.abs(np.frombuffer(out, dtype=np.int16)).max() < 1500
