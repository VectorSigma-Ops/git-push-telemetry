"""Telemetry module for git-push-telemetry."""

from typing import Any


class Telemetry:
    """Simple telemetry emitter."""

    def emit_event(self, event_name: str, data: dict[str, Any]) -> None:  # noqa: VULTURE
        """Emit a telemetry event."""
        # In production, this would send to a telemetry backend
        pass


telemetry = Telemetry()  # noqa: VULTURE
