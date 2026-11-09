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
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.baggage import BaggagePropagator
from opentelemetry.propagators.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
try:
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.urllib import URLLibInstrumentor
    HAS_HTTP_INSTRUMENTATION = True
except ImportError:
    HAS_HTTP_INSTRUMENTATION = False
_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_initialized = False

def init_observability(service_name: str, version: str='0.1.0', environment: str='development', otlp_endpoint: str='http://localhost:4317', log_level: int=logging.INFO, sampling_ratio: float=0.1, enable_http_instrumentation: bool=True) -> None:
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
    resource = Resource.create({SERVICE_NAME: service_name, SERVICE_VERSION: version, DEPLOYMENT_ENVIRONMENT: environment})
    _tracer_provider = TracerProvider(resource=resource, sampler=trace.TraceIdRatioBased(sampling_ratio))
    span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    _tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(_tracer_provider)
    metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=30000)
    _meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(_meter_provider)
    set_global_textmap(TraceContextTextMapPropagator())
    from opentelemetry.propagators.composite import CompositePropagator
    set_global_textmap(CompositePropagator([TraceContextTextMapPropagator(), BaggagePropagator()]))
    LoggingInstrumentor().instrument(set_logging_format=True)
    if enable_http_instrumentation and HAS_HTTP_INSTRUMENTATION:
        RequestsInstrumentor().instrument()
        URLLibInstrumentor().instrument()
    logging.basicConfig(level=log_level, format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "service": "%(name)s", "trace_id": "%(otelTraceID)s", "span_id": "%(otelSpanID)s", "message": "%(message)s"}', datefmt='%Y-%m-%dT%H:%M:%S%z')
    _initialized = True
    logging.getLogger(__name__).info(f'Observability initialized for {service_name} v{version}')

def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer for the given name."""
    return trace.get_tracer_provider().get_tracer(name)

def get_meter(name: str) -> metrics.Meter:
    """Get a meter for the given name."""
    return metrics.get_meter_provider().get_meter(name)

def create_common_metrics(meter: metrics.Meter) -> dict:
    """Create common metrics for HTTP services."""
    return {'http_requests_total': meter.create_counter('http_requests_total', description='Total number of HTTP requests', unit='1'), 'http_request_duration_seconds': meter.create_histogram('http_request_duration_seconds', description='HTTP request latency in seconds', unit='s'), 'active_connections': meter.create_up_down_counter('active_connections', description='Number of active connections', unit='1')}

class HealthChecker:
    """Simple health check registry."""

    def __init__(self):
        self._checks = {}

    def register(self, name: str, check_fn, critical: bool=False):
        """Register a health check function."""
        self._checks[name] = {'fn': check_fn, 'critical': critical}

    def check_liveness(self) -> tuple[bool, dict]:
        """Liveness check - only critical checks."""
        results = {}
        healthy = True
        for name, check in self._checks.items():
            _check_1()
        return (healthy, results)

    def check_readiness(self) -> tuple[bool, dict]:
        """Readiness check - all checks."""
        results = {}
        healthy = True
        for name, check in self._checks.items():
            try:
                result = check['fn']()
                results[name] = {'status': 'pass' if result else 'fail', 'critical': check['critical']}
                if not result:
                    healthy = False
            except Exception as e:
                results[name] = {'status': 'fail', 'error': str(e), 'critical': check['critical']}
                healthy = False
        return (healthy, results)
health_checker = HealthChecker()

def shutdown_observability() -> None:
    """Shutdown observability providers."""
    global _initialized
    if _tracer_provider:
        _tracer_provider.shutdown()
    if _meter_provider:
        _meter_provider.shutdown()
    _initialized = False
if __name__ == '__main__':
    init_observability(service_name='example-service', version='1.0.0', environment='development')
    tracer = get_tracer(__name__)
    meter = get_meter(__name__)
    common_metrics = create_common_metrics(meter)

    def check_db():
        return True

    def check_cache():
        return True
    health_checker.register('database', check_db, critical=True)
    health_checker.register('cache', check_cache, critical=False)
    with tracer.start_as_current_span('example-operation') as span:
        span.set_attribute('example.attribute', 'value')
        common_metrics['http_requests_total'].add(1, {'method': 'GET', 'endpoint': '/health'})
        healthy, results = health_checker.check_readiness()
    shutdown_observability()

def _check_1():
    """Extracted condition helper."""
    if check['critical']:
        try:
            result = check['fn']()
            results[name] = {'status': 'pass' if result else 'fail', 'critical': True}
            if not result:
                healthy = False
        except Exception as e:
            results[name] = {'status': 'fail', 'error': str(e), 'critical': True}
            healthy = False