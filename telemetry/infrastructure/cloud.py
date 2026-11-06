from datetime import datetime, timezone
import json
import requests
from telemetry.infrastructure.models import OutboxModel

class CloudTelemetrySynchronizer:
    def __init__(self, cloud_api_url: str | None):
        self.cloud_api_url = cloud_api_url

    def synchronize(self, limit: int = 100) -> int:
        if not self.cloud_api_url:
            return 0
        published = 0
        events = OutboxModel.select().where(OutboxModel.published_at.is_null()).limit(limit)
        for event in events:
            response = requests.post(f"{self.cloud_api_url.rstrip('/')}/api/v1/telemetry/events",
                json={"event_id": event.event_id, "type": event.event_type,
                      "aggregate_id": event.aggregate_id, "payload": json.loads(event.payload)}, timeout=5)
            response.raise_for_status()
            event.published_at = datetime.now(timezone.utc)
            event.save(only=[OutboxModel.published_at])
            published += 1
        return published
