from peewee import BooleanField, CharField

from shared.infrastructure.database import BaseModel


class AuthorizedNodeModel(BaseModel):
    node_id = CharField(primary_key=True)
    api_key = CharField()
    node_type = CharField()
    active = BooleanField(default=True)


class DevicePermissionModel(BaseModel):
    source_node_id = CharField(index=True)
    target_device_id = CharField()
    device_type = CharField()
    active = BooleanField(default=True)

    class Meta:
        indexes = ((("source_node_id", "target_device_id"), True),)
