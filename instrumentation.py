#!/usr/bin/env python3
"""
OpenTelemetry Instrumentation Template
======================================

Copy this file to your project as instrumentation.py and adapt as needed.
This provides standardized OpenTelemetry setup for Hermes projects.

Usage:
    from instrumentation import init_observability, get_tracer, get_meter
    
    # At app startup
    init_observability(service_name="my-service", version="1.0.0")
    
    # In your code
    tracer = get_tracer(__name__)
    meter = get_meter(__name__)
"""

import logging

# OpenTelemetry imports
from opentelemetry import metrics, trace  # pyright: ignore[reportMissingImports]
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter  # pyright: ignore[reportMissingImports]
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # pyright: ignore[reportMissingImports]
from opentelemetry.instrumentation.logging import LoggingInstrumentor  # pyright: ignore[reportMissingImports]
from opentelemetry.propagate import set_global_textmap  # pyright: ignore[reportMissingImports]
from opentelemetry.propagators.baggage import BaggagePropagator  # pyright: ignore[reportMissingImports]
from opentelemetry.propagators.tracecontext import TraceContextTextMapPropagator  # pyright: ignore[reportMissingImports]
from opentelemetry.sdk.metrics import MeterProvider  # pyright: ignore[reportMissingImports]
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # pyright: ignore[reportMissingImports]
from opentelemetry.sdk.resources import (  # pyright: ignore[reportMissingImports]
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider  # pyright: ignore[reportMissingImports]
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # pyright: ignore[reportMissingImports]

# Optional auto-instrumentation
try:
    from opentelemetry.instrumentation.requests import RequestsInstrumentor  # pyright: ignore[reportMissingImports]
    from opentelemetry.instrumentation.urllib import URLLibInstrumentor  # pyright: ignore[reportMissingImports]
    HAS_HTTP_INSTRUMENTATION = True
except ImportError:
    HAS_HTTP_INSTRUMENTATION = False

# Global state
_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_initialized = False


def init_observability(
    service_name: str,
    version: str = "0.1.0",
    environment: str = "development",
    otlp_endpoint: str = "http://localhost:4317",
    log_level: int = logging.INFO,
    sampling_ratio: float = 0.1,
    enable_http_instrumentation: bool = True,
) -> None:
    """
    Initialize OpenTelemetry observability.
    
    Args:
        service_name: Name of the service (e.g., "ftp5vv3-rate-limiter")
        version: Service version (semver)
        environment: deployment.environment (development, staging, production)
        otlp_endpoint: OTLP gRPC endpoint (default: localhost:4317)
        log_level: Logging level
        sampling_ratio: Trace sampling ratio (0.0 to 1.0)
        enable_http_instrumentation: Auto-instrument HTTP libraries
    """
    global _tracer_provider, _meter_provider, _initialized
    
    if _initialized:
        return
    
    # Create resource
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: version,
        DEPLOYMENT_ENVIRONMENT: environment,
    })
    
    # --- Tracing ---
    _tracer_provider = TracerProvider(
        resource=resource,
        sampler=trace.TraceIdRatioBased(sampling_ratio),
    )
    
    # OTLP Span Exporter
    span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    _tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))  # pyright: ignore[reportOptionalMemberAccess]

    trace.set_tracer_provider(_tracer_provider)  # pyright: ignore[reportOptionalMemberAccess]
    
    # --- Metrics ---
    metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=30000)
    _meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(_meter_provider)
    
    # --- Propagation ---
    set_global_textmap(TraceContextTextMapPropagator())
    # Baggage propagator for custom context
    from opentelemetry.propagators.composite import CompositePropagator  # pyright: ignore[reportMissingImports]
    set_global_textmap(CompositePropagator([TraceContextTextMapPropagator(), BaggagePropagator()]))
    
    # --- Logging Instrumentation ---
    LoggingInstrumentor().instrument(set_logging_format=True)
    
    # --- HTTP Auto-instrumentation ---
    if enable_http_instrumentation and HAS_HTTP_INSTRUMENTATION:
        RequestsInstrumentor().instrument()  # pyright: ignore[reportPossiblyUnboundVariable]
        URLLibInstrumentor().instrument()  # pyright: ignore[reportPossiblyUnboundVariable]
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "service": "%(name)s", "trace_id": "%(otelTraceID)s", "span_id": "%(otelSpanID)s", "message": "%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    
    _initialized = True
    logging.getLogger(__name__).info(f"Observability initialized for {service_name} v{version}")


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer for the given name."""
    return trace.get_tracer_provider().get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    """Get a meter for the given name."""
    return metrics.get_meter_provider().get_meter(name)


# --- Common Metrics ---
def create_common_metrics(meter: metrics.Meter) -> dict:
    """Create common metrics for HTTP services."""
    return {
        "http_requests_total": meter.create_counter(
            "http_requests_total",
            description="Total number of HTTP requests",
            unit="1",
        ),
        "http_request_duration_seconds": meter.create_histogram(
            "http_request_duration_seconds",
            description="HTTP request latency in seconds",
            unit="s",
        ),
        "active_connections": meter.create_up_down_counter(
            "active_connections",
            description="Number of active connections",
            unit="1",
        ),
    }


# --- Context Helpers ---
def get_current_trace_id() -> str | None:
    """Get current trace ID as hex string."""
    span = trace.get_current_span()
    if span and span.get_span_context().trace_id:
        return format(span.get_span_context().trace_id, "032x")
    return None


def get_current_span_id() -> str | None:
    """Get current span ID as hex string."""
    span = trace.get_current_span()
    if span and span.get_span_context().span_id:
        return format(span.get_span_context().span_id, "016x")
    return None


def inject_context(carrier: dict) -> None:
    """Inject current context into carrier (for HTTP headers)."""
    from opentelemetry.propagate import inject
    inject(carrier)


def extract_context(carrier: dict) -> None:
    """Extract context from carrier (from HTTP headers)."""
    from opentelemetry.propagate import extract
    ctx = extract(carrier)
    return ctx


# --- Health Check Helpers ---
class HealthChecker:
    """Simple health check registry."""
    
    def __init__(self):
        self._checks = {}
    
    def register(self, name: str, check_fn, critical: bool = False):
        """Register a health check function."""
        self._checks[name] = {"fn": check_fn, "critical": critical}
    
    def check_liveness(self) -> tuple[bool, dict]:
        """Liveness check - only critical checks."""
        results = {}
        healthy = True
        for name, check in self._checks.items():
            if check["critical"]:
                try:
                    result = check["fn"]()
                    results[name] = {"status": "pass" if result else "fail", "critical": True}
                    if not result:
                        healthy = False
                except Exception as e:
                    results[name] = {"status": "fail", "error": str(e), "critical": True}
                    healthy = False
        return healthy, results
    
    def check_readiness(self) -> tuple[bool, dict]:
        """Readiness check - all checks."""
        results = {}
        healthy = True
        for name, check in self._checks.items():
            try:
                result = check["fn"]()
                results[name] = {"status": "pass" if result else "fail", "critical": check["critical"]}
                if not result:
                    healthy = False
            except Exception as e:
                results[name] = {"status": "fail", "error": str(e), "critical": check["critical"]}
                healthy = False
        return healthy, results


# Global health checker
health_checker = HealthChecker()


def shutdown_observability() -> None:
    """Shutdown observability providers."""
    global _initialized
    if _tracer_provider:
        _tracer_provider.shutdown()
    if _meter_provider:
        _meter_provider.shutdown()
    _initialized = False


# --- Example Usage ---
if __name__ == "__main__":
    # Example: Initialize observability
    init_observability(
        service_name="example-service",
        version="1.0.0",
        environment="development",
    )
    
    tracer = get_tracer(__name__)
    meter = get_meter(__name__)
    
    # Create common metrics
    common_metrics = create_common_metrics(meter)
    
    # Register health checks
    def check_db():
        # Replace with actual DB check
        return True
    
    def check_cache():
        # Replace with actual cache check
        return True
    
    health_checker.register("database", check_db, critical=True)
    health_checker.register("cache", check_cache, critical=False)
    
    # Example traced operation
    with tracer.start_as_current_span("example-operation") as span:
        span.set_attribute("example.attribute", "value")
        
        # Record metric
        common_metrics["http_requests_total"].add(1, {"method": "GET", "endpoint": "/health"})
        
        # Check health
        healthy, results = health_checker.check_readiness()
        print(f"Health: {healthy}, Results: {results}")
    
    shutdown_observability()