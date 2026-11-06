import hmac
from iam.domain.entities import DevicePermission
from iam.infrastructure.models import AuthorizedNodeModel, DevicePermissionModel

class AuthenticationError(PermissionError):
    code = "AUTHENTICATION_FAILED"
class AuthorizationError(PermissionError):
    code = "DEVICE_NOT_AUTHORIZED"

class IamService:
    def authenticate(self, node_id: str, api_key: str) -> None:
        node = AuthorizedNodeModel.get_or_none(
            (AuthorizedNodeModel.node_id == node_id) & AuthorizedNodeModel.active)
        if node is None or not hmac.compare_digest(node.api_key, api_key):
            raise AuthenticationError("Invalid node credentials")

    def authorize_target(self, source_node_id: str, target_device_id: str) -> DevicePermission:
        row = DevicePermissionModel.get_or_none(
            (DevicePermissionModel.source_node_id == source_node_id)
            & (DevicePermissionModel.target_device_id == target_device_id)
            & DevicePermissionModel.active)
        if row is None:
            raise AuthorizationError(f"{source_node_id} cannot control {target_device_id}")
        return DevicePermission(target_device_id, row.device_type)
