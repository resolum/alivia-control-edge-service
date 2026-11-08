"""Un WAV (o un texto) -> transcripción, JSON del LLM y lo que se publicaría por MQTT.

Por defecto NO publica nada. Con --publish pide confirmación por teclado, igual que lo exige el pipeline.

Uso:
    python -m scripts.simulate abre_puerta.wav
    python -m scripts.simulate --text "ya me voy a dormir"
    python -m scripts.simulate abre_puerta.wav --publish      # requiere el broker y mock_actuators
"""

import argparse
import asyncio
import json

from alivia_edge.asr.hallucination import is_hallucination
from alivia_edge.config import VoiceConfig
from alivia_edge.devices.catalog import DeviceCatalog, DeviceStates
from alivia_edge.emergency.detector import EmergencyDetector
from alivia_edge.nlu.contract import InterpreterError
from alivia_edge.nlu.ollama import OllamaInterpreter
from alivia_edge.replies import join_es
from alivia_edge.text import strip_wake, wake_keywords
from scripts.audio_files import read_wav_16k_mono


def transcribe(config: VoiceConfig, wav: str) -> str:
    from alivia_edge.asr.whisper import FasterWhisperTranscriber

    transcriber = FasterWhisperTranscriber(
        config.whisper_model, config.whisper_device, config.whisper_compute_type
    )
    transcript = transcriber.transcribe(read_wav_16k_mono(wav))
    print(
        f"transcripción: {transcript.text!r} (no_speech_prob={transcript.no_speech_prob:.2f})"
    )
    if is_hallucination(transcript, config.no_speech_prob_max):
        raise SystemExit("descartado como alucinación o vacío: no se interpreta")
    return transcript.text


async def publish(config: VoiceConfig, catalog: DeviceCatalog, actions) -> None:
    from alivia_edge.mqtt.bus import PahoActuatorBus

    bus = PahoActuatorBus(config)
    bus.start(asyncio.get_running_loop())
    await asyncio.sleep(1)
    resolved = [catalog.resolve(a.device, a.action) for a in actions]
    results = await asyncio.gather(
        *(
            bus.execute(source_device_id="simulate", spec=s, action=a)
            for s, a in resolved
        )
    )
    for (spec, _), result in zip(resolved, results, strict=True):
        print(f"{spec.name}: {result.status} {result.confirmed_state or ''}")
    bus.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("wav", nargs="?")
    parser.add_argument("--text", help="saltarse a Whisper y usar este texto")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if not args.wav and not args.text:
        parser.error("indica un WAV o --text")

    config = VoiceConfig.from_env()
    catalog = DeviceCatalog.from_file(config.devices_file)
    text = args.text or transcribe(config, args.wav)

    detector = EmergencyDetector(
        config.wake_phrases, config.emergency_words, config.cancel_phrases
    )
    if detector.is_emergency(text):
        raise SystemExit(
            "EMERGENCIA: va directo al cloud; no pasa por el LLM ni por MQTT."
        )
    command = strip_wake(text, wake_keywords(config.wake_phrases))
    interpreter = OllamaInterpreter(
        config.ollama_url, config.ollama_model, config.ollama_timeout_s, catalog
    )
    try:
        result = interpreter.interpret(command, DeviceStates(catalog).snapshot())
    except InterpreterError as error:
        raise SystemExit(f"No te entendí bien, ¿puedes repetirlo? ({error})") from error
    print("JSON del LLM:", json.dumps({"mode": result.mode, "speech": result.speech,
          "actions": [{"device": a.device, "action": a.action} for a in result.actions]}, ensure_ascii=False))  # fmt: skip
    if not result.actions:
        print("pregunta de aclaración:", result.speech)
        return
    phrases = [catalog.resolve(a.device, a.action)[1].confirm for a in result.actions]
    print(f"el edge preguntaría: ¿Quieres que {join_es(phrases)}?")
    for action in result.actions:
        spec, spec_action = catalog.resolve(action.device, action.action)
        print(
            f"MQTT (tras confirmar): {config.command_topic} <- {spec.device_id} {spec_action.api_action}"
        )
    if args.publish and input(
        "¿Confirmas y publico por MQTT? [s/N] "
    ).strip().lower() in ("s", "si", "sí"):
        asyncio.run(publish(config, catalog, result.actions))


if __name__ == "__main__":
    main()
