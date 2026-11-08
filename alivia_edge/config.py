"""Configuración del edge de voz. Todo umbral, timeout, topic, modelo, ruta, URL y puerto llega por entorno."""

import os
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_WAKE_PHRASES = (
    "alivia",
    "oye alivia",
    "ey alivia",
    "hey alivia",
    "oiga alivia",
)
DEFAULT_EMERGENCY_WORDS = ("ayuda", "auxilio")
DEFAULT_CANCEL_PHRASES = ("cancela", "falsa alarma", "estoy bien")
PLACEHOLDER_TOKEN = "changeme"


def _text(name: str, default: str) -> str:
    return os.getenv(name, default)


def _number(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _whole(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _words(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class VoiceConfig:
    # Transporte WebSocket
    ws_host: str = "0.0.0.0"
    ws_port: int = 8765
    ws_path: str = "/ws"
    ws_token: str = ""
    hello_timeout_s: float = 5.0
    ping_interval_s: float = 10.0
    ping_timeout_s: float = 30.0  # 3 intervalos sin respuesta
    max_frames_per_message: int = 4

    # Modelos
    vosk_model_path: str = "models/vosk-model-small-es-0.42"
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "auto"
    whisper_compute_type: str = "default"
    piper_voice_path: str = "models/piper/es_ES-davefx-medium.onnx"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b-instruct-q4_K_M"
    ollama_timeout_s: float = 30.0
    devices_file: str = ""

    # Voz
    wake_phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES
    vad_threshold: float = 0.5
    vad_end_ms: int = 700
    max_utterance_s: float = 15.0
    no_speech_timeout_s: float = 6.0
    preroll_ms: int = 400
    no_speech_prob_max: float = 0.6

    # Confirmación y eco
    confirm_window_s: float = 8.0
    max_reasks: int = 2
    echo_tail_ms: int = 300
    playback_done_margin_s: float = 3.0
    playback_chunk_ms: int = 40
    playback_lead_ms: int = 300

    # MQTT hacia el edge de actuadores
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    network_id: str = "local-network"
    mqtt_command_topic: str = ""
    mqtt_result_topic: str = ""
    actuator_timeout_s: float = 8.0
    edge_id: str = "voice-edge-01"

    # Emergencia
    emergency_words: tuple[str, ...] = DEFAULT_EMERGENCY_WORDS
    cancel_phrases: tuple[str, ...] = DEFAULT_CANCEL_PHRASES
    emergency_cancel_window_s: float = 15.0
    emergency_dedupe_s: float = 10.0
    backend_url: str = "https://api.alivia.example"
    emergency_path: str = "/api/v1/emergencies"
    emergency_api_token: str = PLACEHOLDER_TOKEN
    emergency_timeout_s: float = 3.0
    emergency_inline_attempts: int = 2
    emergency_retry_base_s: float = 2.0
    emergency_retry_max_s: float = 60.0
    emergency_queue_path: str = "data/emergency-queue.db"

    # Estado para /health y /status
    status_path: str = "data/voice-status.json"
    status_interval_s: float = 5.0

    @property
    def command_topic(self) -> str:
        return (
            self.mqtt_command_topic
            or f"alivia/v1/networks/{self.network_id}/actuator-edge/commands"
        )

    @property
    def result_topic(self) -> str:
        return (
            self.mqtt_result_topic
            or f"alivia/v1/networks/{self.network_id}/control-edge/results"
        )

    @property
    def emergency_is_placeholder(self) -> bool:
        host = (urlparse(self.backend_url).hostname or "").lower()
        return (
            not host
            or host.endswith(".example")
            or self.emergency_api_token in ("", PLACEHOLDER_TOKEN)
        )

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        d = cls()
        return cls(
            ws_host=_text("ALIVIA_WS_HOST", d.ws_host),
            ws_port=_whole("ALIVIA_WS_PORT", d.ws_port),
            ws_path=_text("ALIVIA_WS_PATH", d.ws_path),
            ws_token=_text("ALIVIA_WS_TOKEN", d.ws_token),
            hello_timeout_s=_number("ALIVIA_HELLO_TIMEOUT_S", d.hello_timeout_s),
            ping_interval_s=_number("ALIVIA_PING_INTERVAL_S", d.ping_interval_s),
            ping_timeout_s=_number("ALIVIA_PING_TIMEOUT_S", d.ping_timeout_s),
            max_frames_per_message=_whole(
                "ALIVIA_MAX_FRAMES_PER_MESSAGE", d.max_frames_per_message
            ),
            vosk_model_path=_text("ALIVIA_VOSK_MODEL", d.vosk_model_path),
            whisper_model=_text("ALIVIA_WHISPER_MODEL", d.whisper_model),
            whisper_device=_text("ALIVIA_WHISPER_DEVICE", d.whisper_device),
            whisper_compute_type=_text(
                "ALIVIA_WHISPER_COMPUTE_TYPE", d.whisper_compute_type
            ),
            piper_voice_path=_text("ALIVIA_PIPER_VOICE", d.piper_voice_path),
            ollama_url=_text("ALIVIA_OLLAMA_URL", d.ollama_url),
            ollama_model=_text("ALIVIA_OLLAMA_MODEL", d.ollama_model),
            ollama_timeout_s=_number("ALIVIA_OLLAMA_TIMEOUT_S", d.ollama_timeout_s),
            devices_file=_text("ALIVIA_DEVICES_FILE", d.devices_file),
            wake_phrases=_words("ALIVIA_WAKE_PHRASES", d.wake_phrases),
            vad_threshold=_number("ALIVIA_VAD_THRESHOLD", d.vad_threshold),
            vad_end_ms=_whole("ALIVIA_VAD_END_MS", d.vad_end_ms),
            max_utterance_s=_number("ALIVIA_MAX_UTTERANCE_S", d.max_utterance_s),
            no_speech_timeout_s=_number(
                "ALIVIA_NO_SPEECH_TIMEOUT_S", d.no_speech_timeout_s
            ),
            preroll_ms=_whole("ALIVIA_PREROLL_MS", d.preroll_ms),
            no_speech_prob_max=_number(
                "ALIVIA_NO_SPEECH_PROB_MAX", d.no_speech_prob_max
            ),
            confirm_window_s=_number("ALIVIA_CONFIRM_WINDOW_S", d.confirm_window_s),
            max_reasks=_whole("ALIVIA_MAX_REASKS", d.max_reasks),
            echo_tail_ms=_whole("ALIVIA_ECHO_TAIL_MS", d.echo_tail_ms),
            playback_done_margin_s=_number(
                "ALIVIA_PLAYBACK_DONE_MARGIN_S", d.playback_done_margin_s
            ),
            playback_chunk_ms=_whole("ALIVIA_PLAYBACK_CHUNK_MS", d.playback_chunk_ms),
            playback_lead_ms=_whole("ALIVIA_PLAYBACK_LEAD_MS", d.playback_lead_ms),
            mqtt_host=_text("MQTT_HOST", d.mqtt_host),
            mqtt_port=_whole("MQTT_PORT", d.mqtt_port),
            network_id=_text("EDGE_NETWORK_ID", d.network_id),
            mqtt_command_topic=_text("ALIVIA_MQTT_COMMAND_TOPIC", d.mqtt_command_topic),
            mqtt_result_topic=_text("ALIVIA_MQTT_RESULT_TOPIC", d.mqtt_result_topic),
            actuator_timeout_s=_number(
                "ALIVIA_ACTUATOR_TIMEOUT_S", d.actuator_timeout_s
            ),
            edge_id=_text("ALIVIA_EDGE_ID", d.edge_id),
            emergency_words=_words("ALIVIA_EMERGENCY_WORDS", d.emergency_words),
            cancel_phrases=_words("ALIVIA_CANCEL_PHRASES", d.cancel_phrases),
            emergency_cancel_window_s=_number(
                "ALIVIA_EMERGENCY_CANCEL_WINDOW_S", d.emergency_cancel_window_s
            ),
            emergency_dedupe_s=_number(
                "ALIVIA_EMERGENCY_DEDUPE_S", d.emergency_dedupe_s
            ),
            backend_url=_text("ALIVIA_BACKEND_URL", d.backend_url),
            emergency_path=_text("EMERGENCY_PATH", d.emergency_path),
            emergency_api_token=_text("EMERGENCY_API_TOKEN", d.emergency_api_token),
            emergency_timeout_s=_number(
                "ALIVIA_EMERGENCY_TIMEOUT_S", d.emergency_timeout_s
            ),
            emergency_inline_attempts=_whole(
                "ALIVIA_EMERGENCY_INLINE_ATTEMPTS", d.emergency_inline_attempts
            ),
            emergency_retry_base_s=_number(
                "ALIVIA_EMERGENCY_RETRY_BASE_S", d.emergency_retry_base_s
            ),
            emergency_retry_max_s=_number(
                "ALIVIA_EMERGENCY_RETRY_MAX_S", d.emergency_retry_max_s
            ),
            emergency_queue_path=_text(
                "ALIVIA_EMERGENCY_QUEUE_PATH", d.emergency_queue_path
            ),
            status_path=_text("ALIVIA_STATUS_PATH", d.status_path),
            status_interval_s=_number("ALIVIA_STATUS_INTERVAL_S", d.status_interval_s),
        )
