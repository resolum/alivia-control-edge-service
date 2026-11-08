import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_path: str = "control-edge.db"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_enabled: bool = True
    network_id: str = "local-network"
    edge_id: str = "control-edge-01"
    confidence_threshold: float = 0.75
    cloud_api_url: str | None = None
    setup_token: str = "change-me"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=os.getenv("EDGE_DATABASE_PATH", "control-edge.db"),
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_enabled=os.getenv("MQTT_ENABLED", "true").lower() == "true",
            network_id=os.getenv("EDGE_NETWORK_ID", "local-network"),
            edge_id=os.getenv("EDGE_ID", "control-edge-01"),
            confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.75")),
            cloud_api_url=os.getenv("CLOUD_API_URL") or None,
            setup_token=os.getenv("EDGE_SETUP_TOKEN", "change-me"),
        )
