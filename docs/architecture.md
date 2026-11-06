# Arquitectura del Alivia Control Edge Service

## 1. Alcance

`alivia-control-edge-service` es el **Edge de control e interacción** desplegado en la red local de la vivienda. Su responsabilidad es mantener el flujo de control disponible incluso sin Internet:

1. Mantiene una sesión WebSocket bidireccional con el embebido del micrófono.
2. Recibe audio o eventos de captura y devuelve estados, solicitudes de repetición y confirmaciones.
3. Convierte una inferencia válida en un comando de dominio.
4. Publica el comando para el Edge Actuador mediante el broker MQTT local.
5. Correlaciona el resultado del actuador con la solicitud original.
6. Persiste comandos, resultados y eventos pendientes en SQLite.
7. Sincroniza telemetría con Alivia API cuando vuelve la conexión.

El bounded context principal es **Device Control**, una especialización local de **Bienes**. `Telemetry` e `IAM` son capacidades de apoyo con modelos locales propios; no son copias completas de los bounded contexts cloud.

## 2. Decisiones de comunicación

| Enlace | Protocolo | Motivo |
|---|---|---|
| Embebido del micrófono ↔ Control Edge | WebSocket sobre LAN | Canal persistente, bidireccional y de baja latencia para audio, progreso y confirmaciones. |
| Control Edge ↔ Broker local | MQTT | Desacopla la interpretación del comando de su ejecución física y permite operación local. |
| Broker local ↔ Edge Actuador | MQTT | Entrega comandos y resultados aun cuando Cloud no está disponible. |
| Edge Actuador ↔ Firmware actuador | HTTP local o BLE de respaldo | Ejecuta la acción sobre el hardware y recupera su estado real. |
| Control Edge ↔ Alivia API | HTTPS | Descarga configuración y sincroniza telemetría, auditoría y eventos pendientes. |

WebSocket no reemplaza MQTT: WebSocket delimita la comunicación con el embebido del micrófono; MQTT delimita la comunicación asíncrona entre edges.

## 3. C4 nivel 1 — Contexto del sistema

![C4 contexto](diagrams/c4-context.puml)

Actores y sistemas relevantes:

- La persona asistida emite el comando de voz.
- El embebido del micrófono captura audio y mantiene el WebSocket.
- El Control Edge interpreta, valida y orquesta el comando.
- El sistema local de actuación ejecuta la acción física.
- Alivia Cloud administra configuración y recibe telemetría, pero no participa en el camino crítico local.

## 4. C4 nivel 2 — Contenedores

![C4 contenedores](diagrams/c4-container.puml)

El límite de despliegue local contiene:

- **Embedded Microphone**: firmware de captura y reproducción.
- **Control Edge Service**: aplicación Python/Flask de este repositorio.
- **MQTT Broker**: transporte local entre edges.
- **Actuator Edge Service**: procesa comandos dirigidos a actuadores.
- **SQLite Control Edge**: permisos, sesiones, comandos, outbox e inbox.
- **Embedded Actuator**: firmware que maneja el hardware físico.

La indisponibilidad de Cloud no debe impedir el recorrido:

`Micrófono → WebSocket → Control Edge → MQTT → Actuator Edge → Actuador`.

## 5. C4 nivel 3 — Componentes del Control Edge

![C4 componentes](diagrams/c4-component.puml)

### Interfaces

- `MicrophoneWebSocketGateway`: acepta una sesión por dispositivo autorizado, recibe frames y emite respuestas.
- `MqttCommandPublisher`: publica comandos dirigidos al Edge Actuador.
- `MqttResultConsumer`: consume resultados y los entrega al caso de uso de correlación.
- `HealthController`: expone salud y diagnóstico local; no contiene reglas de dominio.

### Aplicación

- `ProcessVoiceCapture`: coordina captura, inferencia, umbral de confianza y creación del comando.
- `DispatchDeviceCommand`: valida autorización, registra el comando y lo publica de forma confiable.
- `HandleExecutionResult`: correlaciona el resultado, actualiza el estado y responde al micrófono.
- `SynchronizePendingEvents`: envía el outbox a Cloud con idempotencia y reintentos.

### Dominio

- `DeviceCommand`: agregado que representa la intención validada y su ciclo de vida.
- `CommandExecution`: ejecución correlacionada con un actuador.
- `TargetDevice`: referencia al dispositivo objetivo autorizado.
- `CommandPolicy`: valida acción, tipo de dispositivo, confianza y transiciones.
- `ExecutionStatus`: `RECEIVED`, `VALIDATED`, `DISPATCHED`, `COMPLETED`, `FAILED`, `EXPIRED`.

### Infraestructura

- Repositorios SQLite para comandos, permisos, inbox, outbox y sesiones.
- Cliente MQTT con QoS, reconexión y correlation ID.
- Cliente HTTPS de Alivia API.
- Adaptador de inferencia local de voz.
- Reloj y generador de identificadores inyectables para pruebas.

## 6. Estructura DDD propuesta

```text
alivia-control-edge-service/
├── app.py
├── bootstrap.py
├── config.py
├── requirements.txt
├── iam/
│   ├── domain/
│   │   └── entities.py
│   ├── application/
│   │   └── services.py
│   ├── infrastructure/
│   │   └── models.py
│   └── interfaces/
│       └── http.py
├── device_control/
│   ├── domain/
│   │   └── entities.py
│   ├── application/
│   │   └── services.py
│   ├── infrastructure/
│   │   ├── messaging.py
│   │   ├── models.py
│   │   └── repositories.py
│   └── interfaces/
│       ├── http.py
│       └── websocket.py
├── telemetry/
│   ├── domain/
│   │   └── entities.py
│   ├── application/
│   │   └── services.py
│   ├── infrastructure/
│   │   ├── cloud.py
│   │   └── models.py
│   └── interfaces/
│       └── http.py
├── shared/
│   ├── domain/
│   │   └── entities.py
│   ├── application/
│   │   └── services.py
│   ├── infrastructure/
│   │   └── database.py              # Peewee, BaseModel y Unit of Work
│   └── interfaces/
│       └── http.py
├── docs/
└── tests/
```

## 7. Contrato WebSocket

Ruta sugerida: `ws://<edge-local>/ws/v1/microphones/{device_id}`. En producción local debe usarse `wss://` si la capacidad del hardware lo permite.

Todos los mensajes de control usan JSON y contienen:

```json
{
  "message_id": "uuid",
  "correlation_id": "uuid",
  "type": "audio.capture.completed",
  "device_id": "microphone-01",
  "occurred_at": "2026-11-06T14:40:35Z",
  "payload": {}
}
```

Mensajes Embedded → Edge:

- `session.hello`: identificación, versión de firmware y capacidades.
- `audio.capture.started`: inicio de captura.
- `audio.chunk`: frame binario asociado al `correlation_id`.
- `audio.capture.completed`: fin de audio.
- `device.health.reported`: batería, conectividad y errores.
- `playback.completed`: confirmación de reproducción.

Mensajes Edge → Embedded:

- `session.accepted` o `session.rejected`.
- `capture.ready`: autorización para enviar audio.
- `command.processing`: progreso perceptible para el usuario.
- `command.repeat_required`: confianza insuficiente o audio inválido.
- `action.completed`: acción confirmada por el actuador.
- `action.failed`: fallo seguro con código traducible a audio.
- `playback.requested`: texto o identificador de audio que debe reproducirse.

Los mensajes deben ser idempotentes por `message_id`. El Edge no ejecuta dos veces un comando con el mismo `correlation_id`.

## 8. Topics MQTT

```text
alivia/v1/networks/{network_id}/actuator-edge/commands
alivia/v1/networks/{network_id}/control-edge/results
alivia/v1/networks/{network_id}/edges/health
```

El payload de comando incluye `command_id`, `correlation_id`, `source_edge_id`, `target_device_id`, `device_type`, `action`, `issued_at` y `expires_at`. Los comandos físicos vencidos se rechazan y nunca se reproducen después de una reconexión tardía.

## 9. Flujo principal

1. El embebido abre el WebSocket y envía `session.hello`.
2. `IAM` valida dispositivo, red y versión del contrato.
3. El embebido transmite el audio usando frames binarios.
4. El adaptador de inferencia produce intención, objetivo y confianza.
5. `CommandPolicy` rechaza ambigüedad o confianza menor al umbral.
6. Se guarda `DeviceCommand` y el evento de outbox en una transacción local.
7. El publicador MQTT envía el comando con expiración y correlación.
8. El Edge Actuador valida el destino, ejecuta y comprueba el estado físico.
9. El resultado vuelve por MQTT y se registra idempotentemente en el inbox.
10. El Control Edge responde por el mismo WebSocket y solicita la confirmación audible.
11. Telemetría sincroniza el evento con Cloud cuando existe conexión.

## 10. Reglas operativas

- El camino crítico de una acción no depende de Internet.
- Un comando ambiguo o con confianza insuficiente nunca acciona hardware.
- Toda acción física tiene `correlation_id`, vencimiento y resultado terminal.
- SQLite usa inbox/outbox para evitar pérdida o duplicación tras reinicios.
- WebSocket tiene heartbeat, límite de tamaño, timeout de captura y reconexión con backoff.
- MQTT usa QoS 1 más deduplicación; QoS por sí solo no garantiza ejecución única.
- La tabla de acceso se conserva localmente y se reemplaza de forma atómica.
- Si el estado físico no puede confirmarse, el resultado es fallo; no se informa éxito optimista.
