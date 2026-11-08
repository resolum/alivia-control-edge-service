import atexit
import logging
from flask import Flask, jsonify, request
from flask_sock import Sock
from flasgger import Swagger

from alivia_edge.http_status import voice_status_api
from config import Settings
from device_control.application.services import DispatchDeviceCommand, HandleExecutionResult
from device_control.infrastructure.messaging import InMemoryCommandBus, MqttCommandBus
from device_control.infrastructure.models import DeviceCommandModel, InboxModel
from device_control.infrastructure.repositories import PeeweeDeviceCommandRepository
from device_control.interfaces.http import device_control_api
from device_control.interfaces.websocket import ConnectionRegistry, MicrophoneWebSocketGateway
from iam.application.services import IamService
from iam.infrastructure.models import AuthorizedNodeModel, DevicePermissionModel
from iam.interfaces.http import iam_api
from shared.infrastructure.database import initialize_database
from shared.interfaces.http import shared_api
from shared.interfaces.openapi import OPENAPI_TEMPLATE
from telemetry.application.services import TelemetryService
from telemetry.infrastructure.cloud import CloudTelemetrySynchronizer
from telemetry.infrastructure.models import OutboxModel
from telemetry.interfaces.http import telemetry_api

logger = logging.getLogger(__name__)

def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config["EDGE_SETTINGS"] = settings
    app.config["SWAGGER"] = {"title": "Alivia Control Edge Service API", "uiversion": 3}
    Swagger(app, template=OPENAPI_TEMPLATE)
    initialize_database(settings.database_path, [AuthorizedNodeModel, DevicePermissionModel,
                                                  DeviceCommandModel, InboxModel, OutboxModel])

    repository = PeeweeDeviceCommandRepository()
    iam = IamService()
    telemetry = TelemetryService()
    synchronizer = CloudTelemetrySynchronizer(settings.cloud_api_url)
    connections = ConnectionRegistry()
    result_service_holder = {}

    def result_handler(payload):
        result_service_holder["service"].execute(payload)

    if settings.mqtt_enabled:
        command_bus = MqttCommandBus(settings.mqtt_host, settings.mqtt_port,
                                     settings.network_id, result_handler)
        command_bus.start()
        atexit.register(command_bus.stop)
    else:
        command_bus = InMemoryCommandBus()

    dispatch = DispatchDeviceCommand(repository, iam, command_bus, telemetry,
                                     settings.confidence_threshold)
    results = HandleExecutionResult(repository, telemetry, connections)
    result_service_holder["service"] = results
    gateway = MicrophoneWebSocketGateway(iam, dispatch, connections)

    app.extensions["command_bus"] = command_bus
    app.extensions["dispatch_service"] = dispatch
    app.extensions["result_service"] = results
    app.extensions["telemetry_synchronizer"] = synchronizer
    app.register_blueprint(shared_api)
    app.register_blueprint(iam_api)
    app.register_blueprint(device_control_api)
    app.register_blueprint(telemetry_api)
    app.register_blueprint(voice_status_api)
    sock = Sock(app)

    @sock.route("/ws/v1/microphones/<device_id>")
    def microphone_socket(socket, device_id):
        gateway.handle(socket, device_id, request.args.get("api_key", ""))

    @app.errorhandler(Exception)
    def handle_error(error):
        code = getattr(error, "code", "INTERNAL_ERROR")
        status = 401 if isinstance(error, PermissionError) else 400 if isinstance(error, ValueError) else 500
        if status == 500:
            logger.exception("Unhandled edge error")
        return jsonify(code=code, message=str(error)), status

    return app
