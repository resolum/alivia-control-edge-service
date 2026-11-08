"""ESP32 falso: se conecta al edge, envía audio de WAV(s) como el micrófono real y recibe/guarda/reproduce la respuesta.

Uso:
    python -m scripts.fake_esp32 --token SECRETO --wav hola.wav --wav abre_puerta.wav --wav si.wav --play

Cada WAV se envía cuando la respuesta anterior terminó de sonar (como lo haría una persona que espera la pregunta).
Mientras tanto envía silencio, porque el micrófono real transmite siempre.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from websockets.asyncio.client import connect

from scripts.audio_files import read_wav_16k_mono, write_wav

FRAME_BYTES = 640  # 20 ms a 16 kHz
FRAMES_PER_MESSAGE = 2


class FakeEsp32:
    def __init__(
        self, url, token, device_id, save_dir, play, playback_rate=16000, log=print
    ):
        self.url, self.token, self.device_id = url, token, device_id
        self.save_dir, self.play, self.rate, self.log = (
            Path(save_dir),
            play,
            playback_rate,
            log,
        )
        self.speaking = False
        self.silence_s = 0.8  # silencio tras cada WAV para que cierre el VAD
        self.heard: list[str] = []  # eventos del parlante, en orden
        self._buffer = bytearray()
        self._utterance = ""
        self._count = 0

    def hello(self) -> dict:
        return {
            "type": "hello", "deviceId": self.device_id, "capabilities": ["microphone", "speaker"],
            "micSampleRate": 16000, "playbackSampleRate": self.rate, "bits": 16, "channels": 1,
            "frameSamples": 320, "token": self.token,
        }  # fmt: skip

    async def run(
        self, wavs: list[str], gap_s: float = 1.0, tail_s: float = 3.0
    ) -> None:
        async with connect(self.url) as ws:
            await ws.send(json.dumps(self.hello()))
            reply = json.loads(await ws.recv())
            if reply.get("type") != "ready":
                raise SystemExit(f"el edge rechazó la conexión: {reply}")
            self.log("conectado (ready)")
            receiver = asyncio.create_task(self._receive(ws))
            try:
                for path in wavs:
                    await self._wait_quiet(gap_s)
                    self.log(f"hablando: {path}")
                    await self._stream(ws, read_wav_16k_mono(path))
                await self._wait_quiet(tail_s)
            finally:
                receiver.cancel()

    async def _stream(self, ws, pcm: bytes) -> None:
        step = FRAME_BYTES * FRAMES_PER_MESSAGE
        pcm += bytes(step * round(self.silence_s / (0.02 * FRAMES_PER_MESSAGE)))
        for offset in range(0, len(pcm), step):
            await ws.send(pcm[offset : offset + step].ljust(step, b"\x00"))
            await asyncio.sleep(0.02 * FRAMES_PER_MESSAGE)  # tiempo real

    async def _wait_quiet(self, seconds: float) -> None:
        """Sigue enviando silencio hasta que el parlante calle `seconds` seguidos."""
        quiet_since = asyncio.get_running_loop().time()
        while True:
            now = asyncio.get_running_loop().time()
            if self.speaking:
                quiet_since = now
            elif now - quiet_since >= seconds:
                return
            await asyncio.sleep(0.05)

    async def _receive(self, ws) -> None:
        async for message in ws:
            if isinstance(message, bytes):
                self._buffer.extend(message)
                continue
            data = json.loads(message)
            kind = data["type"]
            self.heard.append(kind)
            if kind == "audio_begin":
                self.speaking, self._buffer, self._utterance = (
                    True,
                    bytearray(),
                    data["utteranceId"],
                )
                self.log(f"parlante: audio_begin ({data['priority']})")
            elif kind == "audio_end":
                asyncio.create_task(self._finish(ws, data["utteranceId"]))
            elif kind == "audio_cancel":
                self.speaking, self._buffer = False, bytearray()
                self.log("parlante: audio_cancel (se corta la reproducción)")

    async def _finish(self, ws, utterance_id: str) -> None:
        pcm = bytes(self._buffer)
        self._count += 1
        path = self.save_dir / f"respuesta_{self._count:02d}.wav"
        write_wav(path, pcm, self.rate)
        self.log(
            f"parlante: {len(pcm) / 2 / self.rate:.1f} s de audio guardados en {path}"
        )
        player = shutil.which("afplay") or shutil.which("aplay")
        if self.play and player:
            await asyncio.to_thread(subprocess.run, [player, str(path)], check=False)
        else:
            await asyncio.sleep(len(pcm) / 2 / self.rate)
        if self._utterance == utterance_id:  # no fue cancelada mientras sonaba
            await ws.send(
                json.dumps({"type": "playback_done", "utteranceId": utterance_id})
            )
            self.speaking = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", default="ws://localhost:8765/ws")
    parser.add_argument("--token", required=True)
    parser.add_argument("--device-id", default="alivia-mic-01")
    parser.add_argument(
        "--wav", action="append", default=[], help="WAV a enviar (se puede repetir)"
    )
    parser.add_argument("--save-dir", default="out/esp32")
    parser.add_argument(
        "--play", action="store_true", help="reproduce la respuesta (afplay/aplay)"
    )
    args = parser.parse_args()
    esp32 = FakeEsp32(args.url, args.token, args.device_id, args.save_dir, args.play)
    asyncio.run(esp32.run(args.wav))


if __name__ == "__main__":
    main()
