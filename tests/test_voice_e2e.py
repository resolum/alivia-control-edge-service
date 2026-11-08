"""Conversación completa: ESP32 falso (scripts/fake_esp32.py) <-> servidor WebSocket real <-> sesión con fakes."""

import asyncio
import socket

from voice_fakes import FakeBus, Harness, aio, make_config, propose, speech
from websockets.asyncio.client import connect  # noqa: F401  (comprueba que el cliente está disponible)

from alivia_edge.session import Session
from alivia_edge.transport.server import VoiceServer
from scripts.audio_files import write_wav
from scripts.fake_esp32 import FakeEsp32


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@aio
async def test_fake_esp32_talks_to_the_edge_and_gets_spoken_replies(tmp_path):
    harness = Harness(
        {"abre la puerta": propose(("puerta", "open"))},
        bus=FakeBus(),
        config=make_config(confirm_window_s=3.0, no_speech_timeout_s=3.0),
    )
    port = free_port()
    config = make_config(
        ws_host="127.0.0.1", ws_port=port, confirm_window_s=3.0, no_speech_timeout_s=3.0
    )
    server = VoiceServer(
        config, lambda hello, output: Session(hello, output, harness.deps)
    )
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1)

    wavs = []
    for name, text in [
        ("wake", "oye alivia"),
        ("command", "abre la puerta"),
        ("yes", "sí"),
    ]:
        path = tmp_path / f"{name}.wav"
        write_wav(path, speech(text), 16000)
        wavs.append(str(path))
    esp32 = FakeEsp32(
        f"ws://127.0.0.1:{port}/ws",
        "secret",
        "alivia-mic-01",
        tmp_path / "out",
        play=False,
        log=lambda _: None,
    )
    esp32.silence_s = 0.2
    try:
        await asyncio.wait_for(esp32.run(wavs, gap_s=0.15, tail_s=0.6), timeout=20)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert harness.bus.calls == [("alivia-mic-01", "door-01", "OPEN")]
    assert harness.speech.spoken[:2] == [
        "¿Quieres que abra la puerta?",
        "Abriendo la puerta",
    ]
    assert "Listo, la puerta está abierta" in harness.speech.spoken
    saved = sorted(p.name for p in (tmp_path / "out").glob("respuesta_*.wav"))
    assert len(saved) >= 3  # pregunta, "Abriendo..." y resultado, ya como WAV
    assert esp32.heard.count("audio_begin") == esp32.heard.count("audio_end")
