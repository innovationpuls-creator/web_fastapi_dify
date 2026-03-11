class ChatPreStreamError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        upstream_error: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.upstream_error = upstream_error
