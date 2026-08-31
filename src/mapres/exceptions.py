class MapResError(Exception):
    pass

class MissingKeyError(MapResError):
    def __init__(self, key: str, token: str | None = None):
        super().__init__(f"Missing key {key!r}")
        self.key = key
        self.token = token or key
