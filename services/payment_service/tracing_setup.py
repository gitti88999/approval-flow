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
    """N4 — see approval_agent/tracing_setup.py for the full rationale: this lets the app
    continue the same distributed trace Dapr started across the hops Dapr can't see into on its
    own (the app's own outbound calls to its sidecar)."""
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
    if not traceparent:
        return None
    return _propagator.extract({"traceparent": traceparent})


def inject_headers(headers: Optional[dict] = None) -> dict:
    headers = dict(headers or {})
    _propagator.inject(headers)
    return headers
