# Arquitectura del edge de voz

El paquete `alivia_edge/` corre en **un solo proceso asyncio** (`python -m alivia_edge`), junto al servicio Flask
existente (`app.py`), con el que solo comparte dos cosas: los topics MQTT y el archivo de estado para `/health` y `/status`.

```
ESP32 --ws /ws (PCM 16 kHz)--> transport/server ──> session ──┬─> asr (Vosk: activación y emergencia)
      <-- audio_begin/PCM/end --      │                       ├─> audio (VAD + captura) ─> asr (Whisper)
                                      │                       ├─> nlu (Qwen en Ollama, JSON validado)
                                  playback                    ├─> mqtt (comando QoS 1 -> actuadores)
                                  (cola + anti-eco)           ├─> tts (Piper + caché + remuestreo)
                                                              └─> emergency (HTTPS al cloud + cola SQLite)
```

| Paquete | Responsabilidad |
|---|---|
| `config.py` | Toda la configuración llega por entorno (`VoiceConfig.from_env()`). |
| `state_machine.py` | `IDLE → GRABANDO → PROCESANDO → ESPERANDO_CONFIRMACION → EJECUTANDO → IDLE`. Cualquier estado vuelve a IDLE. |
| `session.py` | Una sesión por ESP32: aplica la regla de confirmación y la prioridad de la emergencia. |
| `transport/` | Servidor WebSocket (`server.py`), validación del `hello` (`protocol.py`) y reproducción (`playback.py`). |
| `asr/`, `audio/`, `tts/`, `nlu/` | Adaptadores de Vosk, Whisper, Silero, Piper y Qwen. Sus librerías pesadas se importan al cargar el modelo. |
| `devices/catalog.py` | Tabla única de dispositivos y de frases de voz. Lo que no está ahí se descarta. |
| `mqtt/bus.py` | Publica comandos y espera el resultado real del actuador. |
| `emergency/` | Detector de texto, cola persistente y notificador HTTPS. |

## Regla central

Ninguna acción sobre dispositivos llega a MQTT sin una confirmación explícita, y la aplica el código de `session.py`,
nunca el LLM. "Sí / dale / ok / confirmo" ejecuta; "no / cancela / déjalo" cancela; un matiz ("sí, pero la puerta no")
vuelve a Qwen con las acciones pendientes y se pide confirmar la lista final; el silencio o el vencimiento de la ventana
(8 s desde `playback_done`) cancela. Tras 2 rondas sin acuerdo se cancela todo.

## Flujo de voz

1. Vosk con gramática restringida detecta la palabra de activación. Si la frase trae algo más ("alivia abre la puerta"),
   todo el enunciado va directo a Whisper.
2. Silero VAD cierra la frase tras ~700 ms de silencio.
3. Whisper transcribe; se descartan alucinaciones (`asr/hallucination.py`).
4. Qwen devuelve `{mode, speech, actions}`; `nlu/contract.py` lo valida contra la tabla de dispositivos.
5. El edge pregunta con una plantilla fija ("¿Quieres que abra la puerta?") y espera la confirmación.
6. Tras confirmar, publica en MQTT, dice "Abriendo la puerta" y luego el resultado **real** del actuador.

## Eco

El micrófono y el parlante están en el mismo ESP32 y no hay cancelación de eco. Desde `audio_begin` hasta `playback_done`
más 300 ms, el audio del micrófono no llega a Vosk (activación) ni a la captura de comandos. Un segundo reconocedor con
gramática solo de emergencia escucha siempre.

## Emergencia

Es la excepción a "100 % local" y a la confirmación. Nunca pasa por MQTT, Whisper, Qwen ni el edge de actuadores.

- **Detección:** (1) el reconocedor de emergencia reconoce "alivia ayuda" / "oye alivia auxilio" (y variantes) en la misma
  frase, incluso en un resultado parcial; (2) si la persona dice solo la palabra de activación y luego "ayuda", el texto
  transcrito, sin la palabra de activación, son solo palabras de emergencia. "Ayúdame a abrir la puerta" no dispara.
  Dentro de la ventana de confirmación, "ayuda" o "auxilio" solos también cuentan.
- **Prioridad:** cancela la tarea en curso, las acciones pendientes y la reproducción (`audio_cancel`) y vuelve a IDLE.
- **Envío:** el aviso se guarda primero en SQLite (`ALIVIA_EMERGENCY_QUEUE_PATH`) y se envía por HTTPS con
  `Idempotency-Key = emergency_id`. Si falla, `EmergencyNotifier.run_forever` reintenta con backoff (2 s hasta 60 s) hasta
  que el cloud confirme, incluso tras reiniciar el edge.
- **Voz honesta:** "Pedí ayuda" al detectar; "Tu aviso fue enviado" solo si el cloud confirmó; si no, "No pude enviar el
  aviso, sigo intentando". Nunca promete que alguien va en camino.
- **Cancelación:** durante 15 s, "cancela", "falsa alarma" o "estoy bien" envían `emergency_cancelled`; el aviso no se
  borra, queda marcado para que decida el cuidador.
- **Anti-spam:** una segunda detección dentro de 10 s se ignora.
- **Placeholder:** el endpoint real aún no existe. Mientras `ALIVIA_BACKEND_URL` termine en `.example` o el token sea
  `changeme`, `/health` y `/status` muestran `placeholder / no configurado` y el arranque registra un WARNING.

## Estado: `/health` y `/status`

El pipeline escribe `ALIVIA_STATUS_PATH` cada 5 s (de forma atómica) y el servicio Flask existente lo lee en `/health` y
`/status`: sin IPC. Si el archivo falta o tiene más de 15 s, ambos responden 503 `down`. `/health` devuelve `degraded`
mientras el camino de emergencia no esté `ok`, con los avisos pendientes en cola.

## Integración con el servicio Flask existente

Conviven sin tocarse: `device_control/`, `iam/`, `telemetry/` y `shared/` siguen igual. El pipeline de voz usa los mismos
topics y el mismo contrato de mensajes MQTT (`alivia/v1/networks/{network_id}/actuator-edge/commands` y
`.../control-edge/results`). No pasa por el IAM ni por la base de comandos de ese servicio.
