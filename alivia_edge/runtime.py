"""Arranque del edge de voz: carga los modelos una sola vez y levanta WebSocket, MQTT y avisos de emergencia."""

import asyncio
import logging

from alivia_edge.asr.grammar import emergency_grammar, wake_grammar
from alivia_edge.asr.vosk_recognizer import VoskModel
from alivia_edge.asr.whisper import FasterWhisperTranscriber
from alivia_edge.audio.vad import SileroVad
from alivia_edge.config import VoiceConfig
from alivia_edge.devices.catalog import DeviceCatalog, DeviceStates
from alivia_edge.emergency.detector import EmergencyDetector
from alivia_edge.emergency.notifier import EmergencyNotifier
from alivia_edge.emergency.queue import EmergencyQueue
from alivia_edge.mqtt.bus import PahoActuatorBus
from alivia_edge.nlu.ollama import OllamaInterpreter
from alivia_edge.session import Session, SessionDeps
from alivia_edge.status import StatusReporter
from alivia_edge.transport.server import VoiceServer
from alivia_edge.tts.piper import PiperSynthesizer
from alivia_edge.tts.speech import SpeechLibrary

logger = logging.getLogger(__name__)


async def run(config: VoiceConfig | None = None) -> None:
    config = config or VoiceConfig.from_env()
    loop = asyncio.get_running_loop()

    catalog = DeviceCatalog.from_file(config.devices_file)
    queue = EmergencyQueue(config.emergency_queue_path)
    notifier = EmergencyNotifier(config, queue)
    if not notifier.configured:
        logger.warning(
            "CAMINO DE EMERGENCIA EN PLACEHOLDER: ALIVIA_BACKEND_URL=%s o EMERGENCY_API_TOKEN no son reales. "
            "Los avisos se guardan en %s pero no llegarán a ningún cuidador.",
            config.backend_url,
            config.emergency_queue_path,
        )
    if not config.ws_token:
        raise SystemExit(
            "Falta ALIVIA_WS_TOKEN: sin token el ESP32 no puede autenticarse."
        )

    logger.info("cargando modelos (una sola vez)...")
    vosk = await loop.run_in_executor(None, VoskModel, config.vosk_model_path)
    transcriber = await loop.run_in_executor(
        None,
        FasterWhisperTranscriber,
        config.whisper_model,
        config.whisper_device,
        config.whisper_compute_type,
    )
    synthesizer = await loop.run_in_executor(
        None, PiperSynthesizer, config.piper_voice_path
    )
    interpreter = OllamaInterpreter(
        config.ollama_url, config.ollama_model, config.ollama_timeout_s, catalog
    )
    try:
        await loop.run_in_executor(None, interpreter.warm_up)
    except Exception:  # noqa: BLE001 - un Ollama caído no debe impedir arrancar
        logger.warning(
            "Ollama no respondió al arrancar; se reintentará con la primera orden"
        )

    bus = PahoActuatorBus(config)
    bus.start(loop)
    deps = SessionDeps(
        config=config,
        catalog=catalog,
        states=DeviceStates(catalog),
        transcriber=transcriber,
        interpreter=interpreter,
        speech=SpeechLibrary(synthesizer),
        bus=bus,
        notifier=notifier,
        detector=EmergencyDetector(
            config.wake_phrases, config.emergency_words, config.cancel_phrases
        ),
        wake_recognizer=lambda: vosk.recognizer(wake_grammar(config)),
        emergency_recognizer=lambda: vosk.recognizer(emergency_grammar(config)),
        vad=lambda: SileroVad(config.vad_threshold),
    )
    server = VoiceServer(config, lambda hello, output: Session(hello, output, deps))
    reporter = StatusReporter(config, notifier, server.snapshot, lambda: bus.connected)
    try:
        await asyncio.gather(server.run(), notifier.run_forever(), reporter.run())
    finally:
        bus.stop()
