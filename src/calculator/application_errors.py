"""Typed failures crossing calculator application boundaries."""


class ApplicationError(ValueError):
    """A public application failure with stable machine-readable metadata."""

    error_code: str | None = None

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.context = context

    def public_payload(self) -> dict[str, object]:
        """Return the stable JSON-safe error receipt."""
        payload: dict[str, object] = {"error": str(self)}
        if self.error_code is not None:
            payload["error_code"] = self.error_code
        payload.update(self.context)
        return payload


class NoCompleteEventOrder(ApplicationError):
    """No legal optimizer result has a complete event-ordered timeline."""

    error_code = "no_complete_event_order"
