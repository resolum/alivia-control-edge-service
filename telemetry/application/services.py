import json
from uuid import uuid4

from telemetry.infrastructure.models import OutboxModel


class TelemetryService:
    def record(self, event_type: str, aggregate_id: str, payload: dict) -> None:
        OutboxModel.create(
            event_id=str(uuid4()),
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=json.dumps(payload),
        )
