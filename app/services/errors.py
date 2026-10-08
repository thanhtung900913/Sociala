class ServiceError(Exception):
    """An expected failure that the route can translate into an API response."""

    def __init__(self, payload: dict, status_code: int):
        super().__init__(payload.get("message") or payload.get("error"))
        self.payload = payload
        self.status_code = status_code
