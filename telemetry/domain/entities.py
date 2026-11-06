from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    event_type: str
    aggregate_id: str
    payload: dict
    occurred_at: datetime
