from peewee import CharField, DateTimeField, TextField

from shared.infrastructure.database import BaseModel


class OutboxModel(BaseModel):
    event_id = CharField(primary_key=True)
    event_type = CharField()
    aggregate_id = CharField(index=True)
    payload = TextField()
    published_at = DateTimeField(null=True)
