from peewee import CharField, DateTimeField, FloatField, TextField

from shared.infrastructure.database import BaseModel


class DeviceCommandModel(BaseModel):
    command_id = CharField(primary_key=True)
    correlation_id = CharField(unique=True, index=True)
    source_device_id = CharField()
    target_device_id = CharField()
    device_type = CharField()
    action = CharField()
    confidence = FloatField()
    status = CharField()
    issued_at = DateTimeField()
    expires_at = DateTimeField()
    result_code = CharField(null=True)
    confirmed_state = CharField(null=True)


class InboxModel(BaseModel):
    message_id = CharField(primary_key=True)
    payload = TextField()
