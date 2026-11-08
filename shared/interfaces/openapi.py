OPENAPI_TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title": "Alivia Control Edge Service API",
        "description": (
            "API local del Edge de control. Administra identidad de nodos, permisos, "
            "consulta de comandos y sincronización de telemetría. La comunicación con "
            "el micrófono usa WebSocket y se documenta en la descripción del servicio."
        ),
        "version": "1.0.0",
    },
    "basePath": "/api/v1",
    "schemes": ["http"],
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "tags": [
        {"name": "Shared", "description": "Estado del servicio"},
        {"name": "IAM", "description": "Aprovisionamiento y permisos locales"},
        {"name": "Device Control", "description": "Comandos para dispositivos"},
        {"name": "Telemetry", "description": "Sincronización de eventos offline"},
        {"name": "WebSocket", "description": "Canal bidireccional del micrófono"},
    ],
    "securityDefinitions": {
        "SetupToken": {"type": "apiKey", "name": "X-Setup-Token", "in": "header"}
    },
    "paths": {
        "/health": {
            "get": {
                "tags": ["Shared"],
                "summary": "Obtiene la salud del Edge",
                "responses": {
                    "200": {
                        "description": "Servicio disponible",
                        "schema": {"$ref": "#/definitions/HealthResponse"},
                    }
                },
            }
        },
        "/iam/nodes": {
            "post": {
                "tags": ["IAM"],
                "summary": "Registra o actualiza un nodo",
                "security": [{"SetupToken": []}],
                "parameters": [
                    {
                        "in": "body",
                        "name": "body",
                        "required": True,
                        "schema": {"$ref": "#/definitions/RegisterNodeRequest"},
                    }
                ],
                "responses": {
                    "201": {"description": "Nodo registrado"},
                    "401": {"description": "Setup token inválido"},
                },
            }
        },
        "/iam/permissions": {
            "post": {
                "tags": ["IAM"],
                "summary": "Autoriza a un nodo para controlar un dispositivo",
                "security": [{"SetupToken": []}],
                "parameters": [
                    {
                        "in": "body",
                        "name": "body",
                        "required": True,
                        "schema": {"$ref": "#/definitions/RegisterPermissionRequest"},
                    }
                ],
                "responses": {
                    "201": {"description": "Permiso registrado"},
                    "401": {"description": "Setup token inválido"},
                },
            }
        },
        "/commands/{command_id}": {
            "get": {
                "tags": ["Device Control"],
                "summary": "Consulta un comando",
                "parameters": [
                    {
                        "name": "command_id",
                        "in": "path",
                        "required": True,
                        "type": "string",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Comando encontrado",
                        "schema": {"$ref": "#/definitions/CommandResponse"},
                    },
                    "404": {"description": "Comando no encontrado"},
                },
            }
        },
        "/telemetry/sync": {
            "post": {
                "tags": ["Telemetry"],
                "summary": "Sincroniza eventos pendientes con Cloud",
                "responses": {
                    "200": {
                        "description": "Sincronización completada",
                        "schema": {
                            "type": "object",
                            "properties": {"synchronized": {"type": "integer"}},
                        },
                    }
                },
            }
        },
        "/ws/v1/microphones/{device_id}": {
            "get": {
                "tags": ["WebSocket"],
                "summary": "Abre el canal WebSocket bidireccional del micrófono",
                "description": (
                    "Upgrade a WebSocket. Requiere el query parameter api_key. "
                    "Recibe frames binarios de audio y mensajes voice.intent.recognized."
                ),
                "parameters": [
                    {
                        "name": "device_id",
                        "in": "path",
                        "required": True,
                        "type": "string",
                    },
                    {
                        "name": "api_key",
                        "in": "query",
                        "required": True,
                        "type": "string",
                    },
                ],
                "responses": {
                    "101": {"description": "Switching Protocols"},
                    "401": {"description": "Credenciales inválidas"},
                },
            }
        },
    },
    "definitions": {
        "HealthResponse": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "example": "UP"},
                "edge_id": {"type": "string", "example": "control-edge-01"},
            },
        },
        "RegisterNodeRequest": {
            "type": "object",
            "required": ["node_id", "api_key"],
            "properties": {
                "node_id": {"type": "string", "example": "microphone-01"},
                "api_key": {"type": "string", "example": "device-secret"},
                "node_type": {"type": "string", "example": "MICROPHONE"},
            },
        },
        "RegisterPermissionRequest": {
            "type": "object",
            "required": ["source_node_id", "target_device_id", "device_type"],
            "properties": {
                "source_node_id": {"type": "string", "example": "microphone-01"},
                "target_device_id": {"type": "string", "example": "door-01"},
                "device_type": {"type": "string", "enum": ["DOOR", "WINDOW", "LIGHT"]},
            },
        },
        "CommandResponse": {
            "type": "object",
            "properties": {
                "command_id": {"type": "string"},
                "correlation_id": {"type": "string"},
                "target_device_id": {"type": "string"},
                "device_type": {"type": "string"},
                "action": {"type": "string"},
                "status": {"type": "string"},
                "result_code": {"type": "string", "x-nullable": True},
                "confirmed_state": {"type": "string", "x-nullable": True},
            },
        },
    },
}
