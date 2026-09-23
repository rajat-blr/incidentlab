"""OpenTelemetry setup and structured incident-fixture logs."""

import json
import logging
import os
import re
import uuid

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def request_id_from_header(value: str | None) -> str:
    return value if value and REQUEST_ID_PATTERN.fullmatch(value) else uuid.uuid4().hex


def configure_telemetry(service_name: str) -> tuple[TracerProvider, MeterProvider, LoggerProvider]:
    """Configure one service process to send OTLP/HTTP to the local Collector."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318").rstrip("/")
    resource = Resource.create({"service.name": service_name, "service.namespace": "incidentlab"})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=2))
    )
    trace.set_tracer_provider(tracer_provider)
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", timeout=2),
                export_interval_millis=1000,
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", timeout=2))
    )
    set_logger_provider(logger_provider)
    logger = logging.getLogger("incidentlab.sample")
    logger.setLevel(logging.INFO)
    logger.addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))
    return tracer_provider, meter_provider, logger_provider


def emit_log(event: str, request_id: str | None = None, **fields: object) -> None:
    context = trace.get_current_span().get_span_context()
    record = {
        "event": event,
        "request_id": request_id,
        "trace_id": f"{context.trace_id:032x}" if context.is_valid else None,
    }
    record.update(fields)
    payload = json.dumps(record, sort_keys=True)
    print(payload, flush=True)
    logging.getLogger("incidentlab.sample").info(payload)
