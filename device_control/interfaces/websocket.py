import json
from threading import RLock

class ConnectionRegistry:
    def __init__(self):
        self._connections = {}
        self._lock = RLock()

    def register(self, device_id: str, socket) -> None:
        with self._lock:
            self._connections[device_id] = socket

    def unregister(self, device_id: str, socket) -> None:
        with self._lock:
            if self._connections.get(device_id) is socket:
                self._connections.pop(device_id, None)

    def send(self, device_id: str, message: dict) -> None:
        with self._lock:
            socket = self._connections.get(device_id)
        if socket is not None:
            socket.send(json.dumps(message))

class MicrophoneWebSocketGateway:
    def __init__(self, iam_service, dispatch_service, registry: ConnectionRegistry):
        self.iam, self.dispatch, self.registry = iam_service, dispatch_service, registry

    def handle(self, socket, device_id: str, api_key: str) -> None:
        self.iam.authenticate(device_id, api_key)
        self.registry.register(device_id, socket)
        socket.send(json.dumps({"type": "session.accepted", "device_id": device_id}))
        try:
            while True:
                raw = socket.receive()
                if raw is None:
                    break
                if isinstance(raw, bytes):
                    socket.send(json.dumps({"type": "audio.chunk.accepted", "bytes": len(raw)}))
                    continue
                self._handle_message(socket, device_id, json.loads(raw))
        finally:
            self.registry.unregister(device_id, socket)

    def _handle_message(self, socket, device_id: str, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "ping":
            socket.send(json.dumps({"type": "pong"}))
            return
        if message_type != "voice.intent.recognized":
            socket.send(json.dumps({"type": "message.rejected", "code": "UNSUPPORTED_MESSAGE"}))
            return
        payload = message.get("payload", {})
        command = self.dispatch.execute(
            source_device_id=device_id,
            correlation_id=message["correlation_id"],
            target_device_id=payload["target_device_id"],
            action=payload["action"],
            confidence=float(payload["confidence"]),
        )
        socket.send(json.dumps({"type": "command.dispatched",
                                "correlation_id": command.correlation_id,
                                "payload": {"command_id": command.command_id}}))
