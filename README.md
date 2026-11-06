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
