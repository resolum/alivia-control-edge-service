import asyncio
import json
import socket

from voice_fakes import aio, make_config, until
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from alivia_edge.transport.protocol import Hello
from alivia_edge.transport.server import VoiceServer

HELLO = {
    "type": "hello",
    "deviceId": "esp32-1",
    "capabilities": ["microphone", "speaker"],
    "micSampleRate": 16000,
    "playbackSampleRate": 16000,
    "bits": 16,
    "channels": 1,
    "frameSamples": 320,
    "token": "secret",
}


class RecordingSession:
    def __init__(self, hello: Hello):
        self.hello, self.audio, self.json, self.closed, self.started = (
            hello,
            [],
            [],
            False,
            False,
        )

    async def start(self):
        self.started = True

    async def on_audio(self, pcm):
        self.audio.append(pcm)

    def on_json(self, message):
        self.json.append(message)

    async def close(self):
        self.closed = True

    def snapshot(self):
        return {"deviceId": self.hello.device_id}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def with_server(body, **config):
    port = free_port()
    sessions: list[RecordingSession] = []

    def factory(hello, output):
        sessions.append(RecordingSession(hello))
        return sessions[-1]

    server = VoiceServer(
        make_config(ws_host="127.0.0.1", ws_port=port, hello_timeout_s=0.3, **config),
        factory,
    )
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.1)
    try:
        await body(f"ws://127.0.0.1:{port}", sessions, server)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def handshake(url, hello):
    ws = await connect(f"{url}/ws")
    await ws.send(json.dumps(hello))
    return ws, json.loads(await ws.recv())


@aio
async def test_hello_ready_audio_and_telemetry_reach_the_session():
    async def body(url, sessions, server):
        ws, reply = await handshake(url, HELLO)
        assert reply == {"type": "ready"}
        await ws.send(bytes(1280))
        await ws.send(json.dumps({"type": "playback_done", "utteranceId": "u1"}))
        await until(lambda: sessions and sessions[0].audio and sessions[0].json)
        assert sessions[0].hello.device_id == "esp32-1" and sessions[0].started
        assert sessions[0].json == [{"type": "playback_done", "utteranceId": "u1"}]
        assert server.snapshot() == [{"deviceId": "esp32-1"}]
        await ws.close()
        await until(lambda: sessions[0].closed)

    await with_server(body)


@aio
async def test_bad_token_is_rejected_with_a_reason():
    async def body(url, sessions, server):
        ws, reply = await handshake(url, {**HELLO, "token": "wrong"})
        assert reply == {"type": "error", "reason": "unauthorized"}
        await ws.wait_closed()
        assert sessions == []

    await with_server(body)


@aio
async def test_unsupported_format_and_garbage_hello():
    async def body(url, sessions, server):
        _, reply = await handshake(url, {**HELLO, "micSampleRate": 8000})
        assert reply["reason"] == "unsupported_format"
        ws = await connect(f"{url}/ws")
        await ws.send("esto no es json")
        assert json.loads(await ws.recv())["reason"] == "bad_hello"

    await with_server(body)


@aio
async def test_silent_client_gets_hello_timeout():
    async def body(url, sessions, server):
        ws = await connect(f"{url}/ws")
        assert json.loads(await ws.recv()) == {
            "type": "error",
            "reason": "hello_timeout",
        }

    await with_server(body)


@aio
async def test_wrong_path_is_not_served_and_custom_path_is_configurable():
    async def body(url, sessions, server):
        try:
            await connect(f"{url}/otra")
        except InvalidStatus as error:
            assert error.response.status_code == 404
        else:
            raise AssertionError("debió responder 404")
        ws = await connect(f"{url}/voz")
        await ws.send(json.dumps(HELLO))
        assert json.loads(await ws.recv()) == {"type": "ready"}

    await with_server(body, ws_path="/voz")


@aio
async def test_oversized_or_odd_audio_messages_are_dropped():
    async def body(url, sessions, server):
        ws, _ = await handshake(url, HELLO)
        await ws.send(bytes(641))  # no es múltiplo de muestra
        await ws.send(bytes(640 * 5))  # más de 4 frames
        await ws.send(bytes(640))
        await until(lambda: sessions[0].audio)
        assert [len(a) for a in sessions[0].audio] == [640]

    await with_server(body)


@aio
async def test_reconnect_replaces_the_previous_connection():
    async def body(url, sessions, server):
        first, _ = await handshake(url, HELLO)
        _second, reply = await handshake(url, HELLO)
        assert reply == {"type": "ready"}
        await first.wait_closed()
        await until(lambda: sessions[0].closed)
        assert not sessions[1].closed

    await with_server(body)
