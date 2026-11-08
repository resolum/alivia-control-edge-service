"""Silero VAD. `silero-vad` (y torch/onnxruntime) se importan al cargar el modelo."""


class SileroVad:
    """Un detector por sesión: el modelo guarda estado interno entre frames."""

    frame_samples = 512  # Silero a 16 kHz exige trozos de 512 muestras

    def __init__(self, threshold: float):
        import numpy as np
        import torch
        from silero_vad import load_silero_vad

        self._np = np
        self._torch = torch
        self._model = load_silero_vad(onnx=True)
        self._threshold = threshold

    def is_speech(self, frame: bytes) -> bool:
        samples = (
            self._np.frombuffer(frame, dtype=self._np.int16).astype(self._np.float32)
            / 32768.0
        )
        probability = self._model(self._torch.from_numpy(samples), 16000).item()
        return probability >= self._threshold

    def reset(self) -> None:
        self._model.reset_states()
