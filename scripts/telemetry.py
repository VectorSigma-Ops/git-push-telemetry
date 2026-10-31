"""Telemetry emitter for git-push-telemetry: OTLP spans + JSON Lines deterministic."""

import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

OTEL_AVAILABLE = False


@dataclass
class TelemetryConfig:
    otlp_endpoint: str = "http://localhost:4318/v1/traces"
    otlp_headers: dict[str, str] = field(default_factory=dict)
    jsonl_log_path: str = "~/.hermes/logs/git-push-telemetry.jsonl"
    service_name: str = "git-push-telemetry"
    service_version: str = "1.0.0"


class TelemetryEmitter:
    """Emits deterministic JSON Lines events (OTLP disabled)."""

    def __init__(self, config: TelemetryConfig):
        self.config = config
        self.run_id = str(uuid.uuid4())[:12]
        self.start_time = time.time()
        self._span_stack: list[Any] = []
        self._jsonl_path = os.path.expanduser(config.jsonl_log_path)
        os.makedirs(os.path.dirname(self._jsonl_path), exist_ok=True)
        
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"TelemetryEmitter.__init__ called, run_id={self.run_id}, OTEL_AVAILABLE={OTEL_AVAILABLE}")
        
        self.tracer = None

    def _emit_jsonl(self, event: str, data: dict[str, Any]):
        """Emit deterministic JSON Lines event to stderr and file."""
        entry = {
            "timestamp": time.time(),
            "event": event,
            "data": data,
        }
        # Deterministic key order
        line = json.dumps(entry, sort_keys=True)
        print(line, file=sys.stderr, flush=True)
        # Also write to file
        with open(self._jsonl_path, "a") as f:
            f.write(line + "\n")
    
    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] = None, kind=None):
        """Context manager for JSON Lines start/end events (OTLP disabled)."""
        span_id = str(uuid.uuid4())[:8]
        start = time.time()
        attrs = attributes or {}
        attrs["git.push.run_id"] = self.run_id
        attrs["git.push.span_id"] = span_id
        
        # JSON Lines start event
        self._emit_jsonl(f"git_push_telemetry.{name}.start", attrs)
        
        try:
            yield None
            status = "OK"
        except Exception:
            status = "ERROR"
            raise
        finally:
            duration_ms = round((time.time() - start) * 1000, 2)
            end_attrs = {**attrs, "duration_ms": duration_ms, "status": status}
            
            # JSON Lines end event
            self._emit_jsonl(f"git_push_telemetry.{name}.end", end_attrs)
    
    def event(self, name: str, data: dict[str, Any]):
        """Emit a standalone JSON Lines event (no span)."""
        data["run_id"] = self.run_id
        self._emit_jsonl(f"git_push_telemetry.{name}", data)
    
    def get_run_id(self) -> str:
        return self.run_id
    
    def get_elapsed_ms(self) -> float:
        return round((time.time() - self.start_time) * 1000, 2)


def create_emitter(config_dict: dict[str, Any] = None) -> TelemetryEmitter:
    """Factory function for creating emitter from config dict."""
    config = TelemetryConfig(**(config_dict or {}))
    return TelemetryEmitter(config)
