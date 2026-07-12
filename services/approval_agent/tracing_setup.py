import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_propagator = TraceContextTextMapPropagator()
_tracer = None


def configure_tracing(service_name: str):
    """N4 — exports spans to Jaeger over OTLP. Dapr already auto-traces its own sidecar-mediated
    hops (service invocation, pub/sub delivery); this lets the app continue that same trace
    across the hops Dapr can't see into on its own (the app's own outbound calls to its sidecar,
    and the LLM call), so the whole submit -> evaluate -> pay journey is one trace, not several
    disconnected ones."""
    global _tracer
    if _tracer is not None:
        return _tracer
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "jaeger:4317")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    return _tracer


def get_tracer():
    return trace.get_tracer_provider().get_tracer(__name__)


def extract_context(traceparent: Optional[str]) -> Optional[Context]:
    """Builds a parent Context from a raw W3C traceparent string — Dapr embeds this in the
    CloudEvent envelope for pub/sub deliveries (event_envelope['traceparent']) and forwards it as
    an HTTP header on service-invocation calls."""
    if not traceparent:
        return None
    return _propagator.extract({"traceparent": traceparent})


def inject_headers(headers: Optional[dict] = None) -> dict:
    """Adds a traceparent header derived from the current active span, so the next hop's Dapr
    sidecar (or our own outbound call) continues the same trace instead of starting a new one."""
    headers = dict(headers or {})
    _propagator.inject(headers)
    return headers
