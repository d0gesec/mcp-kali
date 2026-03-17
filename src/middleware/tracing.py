"""OpenTelemetry tracing for MCP tool calls."""
import logging
import os
import struct
import sys

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

log = logging.getLogger("pownie-kali-mcp")

# Default endpoint: Tempo service on the Docker network
_DEFAULT_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "tempo:4317")


def init_tracer(
    service_name: str = "pownie-kali-mcp",
    endpoint: str | None = None,
) -> trace.Tracer:
    """Initialize OTLP tracer. Returns tracer instance.

    If Tempo is unreachable or OTLP packages are missing, returns a no-op tracer
    so the server keeps working without tracing.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(
            endpoint=endpoint or _DEFAULT_ENDPOINT,
            insecure=True,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        log.info("OTLP tracer initialized: endpoint=%s", endpoint or _DEFAULT_ENDPOINT)
    except Exception as exc:
        log.warning("OTLP exporter unavailable, tracing disabled: %s", exc)

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def reconstruct_context(trace_id_hex: str, parent_span_id_hex: str) -> Context:
    """Rebuild an OpenTelemetry Context from hex trace_id and span_id.

    Used to attach MCP server spans as children of the PreToolUse hook's root span.
    """
    trace_id = int(trace_id_hex, 16)
    span_id = int(parent_span_id_hex, 16) if parent_span_id_hex else 0

    span_ctx = SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return trace.set_span_in_context(NonRecordingSpan(span_ctx))
