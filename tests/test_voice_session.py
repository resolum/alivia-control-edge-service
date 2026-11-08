import asyncio

import pytest
from voice_fakes import (
    FakeBus,
    FakeNotifier,
    Harness,
    aio,
    clarify,
    make_config,
    propose,
    silence,
    until,
)

from alivia_edge.nlu.contract import InvalidLlmOutput

OPEN_DOOR = propose(("puerta", "open"))
RULES = {"abre la puerta": OPEN_DOOR}


async def ask_to_open_door(h: Harness) -> None:
    await h.say("oye alivia")
    await h.say("abre la puerta")
    await until(lambda: "¿Quieres que abra la puerta?" in h.speech.spoken)
    await h.listening()


@aio
async def test_confirmed_command_reaches_the_actuator_once():
    async with Harness(RULES) as h:
        await ask_to_open_door(h)
        assert h.bus.calls == []  # nada se ejecuta antes de confirmar
        await h.say("sí")
        await until(lambda: "Listo, la puerta está abierta" in h.speech.spoken)
        assert h.bus.calls == [("esp32-test", "door-01", "OPEN")]
        assert "Abriendo la puerta" in h.speech.spoken
        assert h.session.state.value == "IDLE"


@aio
async def test_command_in_the_same_breath_as_the_wake_word():
    async with Harness(RULES) as h:
        await h.say("alivia abre la puerta")
        await until(lambda: "¿Quieres que abra la puerta?" in h.speech.spoken)
        assert h.bus.calls == []


@aio
async def test_silence_cancels_and_never_executes():
    async with Harness(RULES) as h:
        await ask_to_open_door(h)
        await asyncio.sleep(0.45)
        for _ in range(3):
            await h.session.on_audio(silence(1))
        await until(lambda: "No te escuché, cancelé la acción" in h.speech.spoken)
        assert h.bus.calls == []
        assert h.session.state.value == "IDLE"


@aio
async def test_negative_reply_cancels():
    async with Harness(RULES) as h:
        await ask_to_open_door(h)
        await h.say("no, déjalo")
        await until(lambda: "Listo, no hice nada" in h.speech.spoken)
        assert h.bus.calls == []


@aio
async def test_nuance_goes_to_the_llm_and_asks_again_with_the_final_list():
    rules = {
        "abre la puerta y enciende la luz": propose(
            ("puerta", "open"), ("luz_cuarto", "on")
        ),
        "si pero la puerta no": propose(("luz_cuarto", "on")),
    }
    async with Harness(rules) as h:
        await h.say("oye alivia")
        await h.say("abre la puerta y enciende la luz")
        await until(
            lambda: (
                "¿Quieres que abra la puerta y encienda la luz del cuarto?"
                in h.speech.spoken
            )
        )
        await h.listening()
        await h.say("sí, pero la puerta no")
        await until(
            lambda: "¿Quieres que encienda la luz del cuarto?" in h.speech.spoken
        )
        _text, pending, _ = h.interpreter.calls[-1]
        assert [a.device for a in pending] == ["puerta", "luz_cuarto"]
        assert h.bus.calls == []  # volvió a pedir confirmación de la lista final
        await h.listening()
        await h.say("sí")
        await until(
            lambda: "Listo, la luz del cuarto está encendida" in h.speech.spoken
        )
        assert h.bus.calls == [("esp32-test", "light-01", "TURN_ON")]


@aio
async def test_clarify_answer_keeps_the_context():
    rules = {
        "hace calor": clarify("¿Quieres que abra la ventana?"),
        "si": propose(("ventana", "open")),
    }
    async with Harness(rules) as h:
        await h.say("oye alivia")
        await h.say("hace calor")
        await until(lambda: "¿Quieres que abra la ventana?" in h.speech.spoken)
        await h.listening()
        await h.say("sí")
        await until(lambda: "¿Quieres que abra la ventana?" in h.speech.spoken[1:])
        assert 'pidió "hace calor"' in h.interpreter.calls[-1][2]
        assert h.bus.calls == []


@aio
async def test_invalid_llm_output_executes_nothing():
    async with Harness(
        {"abre la puerta": InvalidLlmOutput("dispositivo desconocido")}
    ) as h:
        await h.say("oye alivia")
        await h.say("abre la puerta")
        await until(lambda: "No te entendí bien, ¿puedes repetirlo?" in h.speech.spoken)
        assert h.bus.calls == []
        await h.idle()


@aio
async def test_hallucination_is_discarded():
    async with Harness(RULES) as h:
        await h.say("oye alivia")
        await h.say("gracias por ver el video")
        await until(lambda: "No te entendí bien, ¿puedes repetirlo?" in h.speech.spoken)
        assert h.interpreter.calls == []


@aio
@pytest.mark.parametrize(
    "status,sentence",
    [
        ("error", "No pude abrir la puerta"),
        ("timeout", "No pude confirmar que se completó: abrir la puerta"),
    ],
)
async def test_real_actuator_result_decides_what_is_said(status, sentence):
    async with Harness(RULES, bus=FakeBus(status)) as h:
        await ask_to_open_door(h)
        await h.say("dale")
        await until(lambda: sentence in h.speech.spoken)
        assert not any(p.startswith("Listo") for p in h.speech.spoken)


@aio
async def test_microphone_is_ignored_while_the_reply_is_playing():
    async with Harness(RULES, auto_done=False) as h:
        await h.say("oye alivia")
        await h.say("abre la puerta")
        await until(lambda: "¿Quieres que abra la puerta?" in h.speech.spoken)
        calls = len(h.interpreter.calls)
        await h.say(
            "oye alivia cierra la puerta"
        )  # eco: suena la respuesta, no se procesa
        await asyncio.sleep(0.05)
        assert len(h.interpreter.calls) == calls
        assert h.session.snapshot()["speaking"]


# --- emergencia -------------------------------------------------------------------------------


@aio
async def test_emergency_in_the_same_phrase_skips_mqtt_whisper_and_llm():
    async with Harness(RULES) as h:
        await h.say("oye alivia ayuda")
        await until(lambda: "Tu aviso fue enviado" in h.speech.spoken)
        assert h.notifier.notified == [("esp32-test", "oye alivia ayuda")]
        assert (
            h.bus.calls == []
            and h.transcriber.calls == []
            and h.interpreter.calls == []
        )
        assert h.speech.spoken[0] == "Pedí ayuda"


@aio
async def test_emergency_in_two_steps_is_detected_after_transcription():
    async with Harness(RULES) as h:
        await h.say("oye alivia")
        await h.say("auxilio")
        await until(lambda: h.notifier.notified)
        assert h.interpreter.calls == [] and h.bus.calls == []


@aio
async def test_help_me_open_the_door_is_not_an_emergency():
    rules = {"ayudame a abrir la puerta": OPEN_DOOR}
    async with Harness(rules) as h:
        await h.say("oye alivia")
        await h.say("ayúdame a abrir la puerta")
        await until(lambda: "¿Quieres que abra la puerta?" in h.speech.spoken)
        assert h.notifier.notified == []


@aio
async def test_emergency_interrupts_playback_and_clears_the_pending_action():
    async with Harness(RULES, auto_done=False) as h:
        await h.say("oye alivia")
        await h.say("abre la puerta")
        await until(lambda: "audio_begin" in h.output.types())
        await h.say("oye alivia ayuda")  # mientras suena la pregunta
        await until(lambda: "audio_cancel" in h.output.types())
        await until(lambda: h.notifier.notified)
        assert h.session.state.value == "IDLE"
        assert h.bus.calls == []
        h.output.auto_done = True
        await h.say("sí")
        await asyncio.sleep(0.05)
        assert h.bus.calls == []  # la acción pendiente murió con la emergencia


@aio
async def test_bare_help_word_counts_inside_the_confirmation_window():
    async with Harness(RULES) as h:
        await ask_to_open_door(h)
        await h.say("ayuda")
        await until(lambda: h.notifier.notified)
        assert h.bus.calls == []
        assert h.notifier.notified[0][1] == "ayuda"


@aio
async def test_repeated_detection_is_ignored_for_ten_seconds():
    async with Harness(RULES) as h:
        await h.say("oye alivia ayuda")
        await until(lambda: "Tu aviso fue enviado" in h.speech.spoken)
        await h.idle()
        await h.say("oye alivia ayuda")
        await asyncio.sleep(0.05)
        assert len(h.notifier.notified) == 1


@aio
async def test_voice_replies_are_honest_when_the_cloud_is_unreachable():
    async with Harness(RULES, notifier=FakeNotifier(delivered=False)) as h:
        await h.say("alivia auxilio")
        await until(
            lambda: "No pude enviar el aviso, sigo intentando" in h.speech.spoken
        )
        assert "Tu aviso fue enviado" not in h.speech.spoken


@aio
async def test_false_alarm_phrase_cancels_the_emergency_inside_the_window():
    async with Harness(RULES) as h:
        await h.say("oye alivia ayuda")
        await until(lambda: "Tu aviso fue enviado" in h.speech.spoken)
        await h.idle()
        await h.say("falsa alarma")
        await until(lambda: h.notifier.cancelled)
        assert h.notifier.cancelled == ["em-1"]


@aio
async def test_cancel_phrase_without_an_emergency_does_nothing():
    async with Harness(RULES) as h:
        await h.say("falsa alarma")
        await asyncio.sleep(0.05)
        assert h.notifier.cancelled == []


@aio
async def test_emergency_never_publishes_to_mqtt():
    from alivia_edge.mqtt.bus import PahoActuatorBus

    class ForbiddenMqttClient:
        published = False

        def publish(self, *args, **kwargs):
            self.published = True
            raise AssertionError("la emergencia no puede publicar en MQTT")

    bus = PahoActuatorBus(make_config())
    client = bus._client = ForbiddenMqttClient()
    async with Harness(RULES, bus=bus) as h:
        await h.say("oye alivia ayuda")
        await until(lambda: "Tu aviso fue enviado" in h.speech.spoken)
        await h.say("oye alivia")
        await h.say("auxilio")
        await asyncio.sleep(0.05)
        assert len(h.notifier.notified) == 1
        assert not client.published


@aio
async def test_disconnect_discards_pending_actions():
    async with Harness(RULES) as h:
        await ask_to_open_door(h)
    assert h.bus.calls == []
