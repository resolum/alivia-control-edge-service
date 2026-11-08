import asyncio

from voice_fakes import FakeOutput, FakeSpeech, aio, make_config, until

from alivia_edge.transport.playback import Playback


def build(**config):
    output, speech = FakeOutput(auto_done=False), FakeSpeech()
    playback = Playback(output, speech, 16000, make_config(**config))
    playback.start()
    return playback, output, speech


@aio
async def test_sequence_begin_binaries_end_then_done_opens_the_window():
    playback, output, _ = build()
    finished = []
    playback.on_finished = finished.append
    uid = playback.enqueue("hola")
    await until(lambda: "audio_end" in output.types())
    types = output.types()
    assert (
        types == ["audio_begin", "audio_end"] and output.audio_chunks == 5
    )  # 100 ms en trozos de 20 ms
    assert (
        output.messages[0]["sampleRate"] == 16000
        and output.messages[0]["priority"] == "normal"
    )
    assert playback.is_gated() and not finished
    playback.on_playback_done(uid)
    await until(lambda: finished == [uid])
    await playback.stop()


@aio
async def test_gate_stays_closed_until_playback_done_plus_tail():
    playback, output, _ = build(echo_tail_ms=150)
    uid = playback.enqueue("hola")
    await until(lambda: "audio_end" in output.types())
    await asyncio.sleep(0.2)
    assert playback.is_gated()  # sigue sonando en el ESP32 aunque ya se envió todo
    playback.on_playback_done(uid)
    await until(lambda: playback._current is None)
    assert playback.is_gated()  # cola de 150 ms
    await asyncio.sleep(0.2)
    assert not playback.is_gated()
    await playback.stop()


@aio
async def test_missing_playback_done_is_assumed_after_the_margin():
    playback, _output, _ = build(playback_done_margin_s=0.1)
    finished = []
    playback.on_finished = finished.append
    playback.enqueue("hola")
    await until(lambda: finished, timeout=2)
    await playback.stop()


@aio
async def test_emergency_goes_to_the_front_and_cancel_all_cuts_playback():
    playback, output, speech = build()
    playback.enqueue("primera")
    await until(lambda: "audio_begin" in output.types())
    playback.enqueue("segunda")
    playback.enqueue("urgente", priority="emergency")
    await playback.cancel_all()
    assert output.messages[-1]["type"] == "audio_cancel"
    await asyncio.sleep(0.05)
    assert speech.spoken == ["primera"]  # la cola se vació
    playback.enqueue("después", priority="emergency")
    await until(lambda: speech.spoken == ["primera", "después"])
    assert [m for m in output.messages if m["type"] == "audio_begin"][-1][
        "priority"
    ] == "emergency"
    await playback.stop()


@aio
async def test_sending_is_paced_ahead_of_real_time_by_a_bounded_lead():
    playback, output, _speech = build(playback_lead_ms=40, playback_chunk_ms=20)
    started = asyncio.get_running_loop().time()
    playback.enqueue("hola")
    await until(lambda: "audio_end" in output.types())
    elapsed = asyncio.get_running_loop().time() - started
    assert (
        0.04 <= elapsed < 0.2
    )  # 100 ms de audio: se adelanta ~40 ms, no lo manda todo de golpe
    await playback.stop()
