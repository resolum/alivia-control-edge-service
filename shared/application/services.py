class HealthService:
    def status(self, edge_id: str) -> dict:
        return {"status": "UP", "edge_id": edge_id}
