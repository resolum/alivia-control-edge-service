import json

import pytest
from voice_fakes import FRAME_BYTES, FakeVad, silence, speech

from alivia_edge.asr.hallucination import is_hallucination
from alivia_edge.audio.frames import Capture
from alivia_edge.devices.catalog import DeviceCatalog, DeviceStates
from alivia_edge.interfaces import Transcript
from alivia_edge.nlu.contract import InvalidLlmOutput, parse_llm_output, response_schema
from alivia_edge.nlu.prompt import build_messages, build_system_prompt

CATALOG = DeviceCatalog()


def raw(**fields):
    return json.dumps(
        {
            "mode": "propose",
            "speech": "¿Abro la puerta?",
            "actions": [{"device": "puerta", "action": "open"}],
            **fields,
        }
    )


def test_valid_proposal():
    result = parse_llm_output(raw(), CATALOG)
    assert result.mode == "propose"
    assert [(a.device, a.action) for a in result.actions] == [("puerta", "open")]


def test_clarify_drops_actions():
    result = parse_llm_output(raw(mode="clarify", speech="¿Cuál?"), CATALOG)
    assert result.mode == "clarify" and result.actions == ()


@pytest.mark.parametrize(
    "bad",
    [
        "no es json",
        "[]",
        raw(mode="execute"),
        raw(actions=[]),
        raw(actions=[{"device": "garaje", "action": "open"}]),
        raw(actions=[{"device": "puerta", "action": "on"}]),
        raw(
            actions=[
                {"device": "puerta", "action": "open"},
                {"device": "puerta", "action": "close"},
            ]
        ),
        raw(actions=[{"device": "puerta"}]),
        raw(speech=7),
        raw(mode="clarify", speech=""),
        raw(speech="palabra " * 60),
    ],
)
def test_invalid_output_is_rejected(bad):
    with pytest.raises(InvalidLlmOutput):
        parse_llm_output(bad, CATALOG)


def test_schema_only_allows_catalog_devices():
    schema = response_schema(CATALOG)
    assert schema["properties"]["actions"]["items"]["properties"]["device"]["enum"] == [
        "puerta",
        "ventana",
        "luz_cuarto",
    ]


def test_prompt_lists_devices_states_modes_and_examples():
    states = DeviceStates(CATALOG)
    states.update("puerta", "OPEN")
    prompt = build_system_prompt(CATALOG, states.snapshot())
    assert "puerta: acciones open, close; estado actual: abierta" in prompt
    assert "propose" in prompt and "clarify" in prompt
    assert prompt.count("Persona: ") >= 8
    messages = build_messages(CATALOG, states.snapshot(), "sí pero la puerta no", ())
    assert (
        messages[0]["role"] == "system"
        and "sí pero la puerta no" in messages[1]["content"]
    )


@pytest.mark.parametrize(
    "text,prob,logprob,junk",
    [
        ("", 0.0, 0.0, True),
        ("Gracias por ver el video", 0.0, 0.0, True),
        ("Subtítulos realizados por la comunidad de Amara.org", 0.0, 0.0, True),
        ("sí sí sí sí sí sí sí", 0.0, 0.0, True),
        ("abre la puerta", 0.9, -1.8, True),
        ("abre la puerta", 0.9, -0.3, False),
        ("abre la puerta", 0.1, -0.3, False),
    ],
)
def test_hallucination_filter(text, prob, logprob, junk):
    assert is_hallucination(Transcript(text, prob, logprob), 0.6) is junk


def test_capture_waits_for_voice_and_keeps_a_little_preroll():
    capture = Capture(FakeVad(), end_ms=30, preroll_ms=20, max_s=5)
    capture.feed(silence(5))
    assert not capture.speech_started
    capture.feed(speech("abre") + silence(4))
    assert capture.finished
    assert capture.audio.startswith(bytes(FRAME_BYTES * 2))  # 20 ms de pre-roll
    assert b"abre" in capture.audio


def test_capture_is_capped():
    capture = Capture(FakeVad(), end_ms=1000, preroll_ms=10, max_s=0.05)
    capture.feed(speech("x" * 5000))
    assert capture.finished and len(capture.audio) <= FRAME_BYTES * 8
