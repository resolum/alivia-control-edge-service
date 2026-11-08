# Alivia Control Edge Service

Servicio local responsable de interpretar, validar y orquestar comandos para los dispositivos Alivia sin depender de una conexión permanente a Internet.

## Ejecución local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Para desarrollar sin un broker MQTT, exportar `MQTT_ENABLED=false`.

## Aprovisionamiento mínimo

```http
POST /api/v1/iam/nodes
POST /api/v1/iam/permissions
GET  /api/v1/health
GET  /api/v1/commands/{command_id}
WS   /ws/v1/microphones/{device_id}?api_key={api_key}
```

La documentación interactiva Swagger UI está disponible en:

```text
http://localhost:5001/apidocs/
```

La especificación OpenAPI se expone como JSON en `http://localhost:5001/apispec_1.json`.

Los endpoints de aprovisionamiento IAM requieren el header `X-Setup-Token`, cuyo valor se configura mediante `EDGE_SETUP_TOKEN`.

Mensaje WebSocket mínimo para despachar una intención ya reconocida:

```json
{
  "type": "voice.intent.recognized",
  "correlation_id": "request-001",
  "payload": {
    "target_device_id": "door-01",
    "action": "OPEN",
    "confidence": 0.94
  }
}
```

## Pruebas

```bash
pytest -q
```

## Edge de voz (`alivia_edge/`)

Pipeline de voz local: recibe el audio de un ESP32 por WebSocket, entiende la orden, pide confirmación, publica por MQTT
y responde con voz por el mismo WebSocket. Arquitectura y decisiones en [`docs/arquitectura-voz.md`](docs/arquitectura-voz.md);
contrato con el ESP32 en [`docs/protocolo-websocket.md`](docs/protocolo-websocket.md) (idéntico en el repo `embebido`).

### Dependencias: dos archivos

| Archivo | Contenido | Lo instala el CI |
|---|---|---|
| `requirements.txt` | Flask, websockets, paho-mqtt, rapidfuzz, numpy, pytest… (versiones fijadas) | Sí |
| `requirements-ml.txt` | `vosk`, `faster-whisper`, `silero-vad` (arrastra torch), `onnxruntime`, `piper-tts` | No |

Los módulos pesados se importan al construir cada adaptador, detrás de las interfaces de `alivia_edge/interfaces.py`;
los tests usan fakes y no necesitan modelos ni GPU.

### Modelos

```bash
pip install -r requirements.txt -r requirements-ml.txt

# Vosk (reconocedor de palabra de activación y emergencia)
mkdir -p models && cd models
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip && unzip vosk-model-small-es-0.42.zip

# Piper (voz): descarga el .onnx y su .onnx.json en models/piper/
python -m piper.download_voices es_ES-davefx-medium --data-dir models/piper   # o desde huggingface.co/rhasspy/piper-voices

# Qwen2.5 3B Instruct Q4 en Ollama
ollama pull qwen2.5:3b-instruct-q4_K_M
```

`faster-whisper` descarga `large-v3-turbo` la primera vez que arranca. Los nombres exactos de los modelos son
configurables (`ALIVIA_VOSK_MODEL`, `ALIVIA_WHISPER_MODEL`, `ALIVIA_PIPER_VOICE`, `ALIVIA_OLLAMA_MODEL`).

### Ejecución

```bash
cp .env.example .env            # edita ALIVIA_WS_TOKEN y, cuando exista, el endpoint de emergencia
set -a; source .env; set +a
mosquitto &                     # broker MQTT
python -m alivia_edge           # pipeline de voz (WebSocket en :8765/ws)
python app.py                   # servicio Flask: /health y /status del pipeline en :5001
```

### Camino de emergencia: placeholder

El endpoint real de emergencias **aún no existe**. `.env.example` trae `ALIVIA_BACKEND_URL=https://api.alivia.example`,
`EMERGENCY_PATH=/api/v1/emergencies` y `EMERGENCY_API_TOKEN=changeme` (el dominio `.example` nunca resuelve, así que no
sale tráfico real). Mientras sigan así, el arranque registra un WARNING y `/health` y `/status` muestran
`placeholder / no configurado`. **Hay que reemplazarlos cuando exista el endpoint real.** Los avisos que se generen en
tanto quedan en la cola persistente y se enviarán cuando haya un destino válido.

### Pruebas

```bash
pytest -q                                    # suite completa con fakes (sin modelos)
ruff check . && ruff format --check .

# Pruebas manuales (scripts/):
python -m scripts.simulate abre_puerta.wav   # WAV -> transcripción -> JSON del LLM -> MQTT (no publica sin --publish)
python -m scripts.simulate --text "ya me voy a dormir"
python -m scripts.mock_actuators --mode ok   # edge de actuadores falso: ok | error | timeout
python -m scripts.fake_esp32 --token $ALIVIA_WS_TOKEN --wav hola.wav --wav abre_puerta.wav --wav si.wav --play
```
