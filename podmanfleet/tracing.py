import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI
from loguru import logger
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from podmanfleet.config import settings

if TYPE_CHECKING:
    from loguru import HandlerConfig


def _otel_enabled() -> bool:
    return bool(settings.OTEL_EXPORTER_OTLP_ENDPOINT)


def setup_otel() -> None:
    if not _otel_enabled():
        logger.warning("OpenTelemetry is disabled, no OTEL_EXPORTER_OTLP_ENDPOINT provided")
        return

    logger.info("Initializing OpenTelemetry")
    resource = Resource.create({
        "service.name": settings.OTEL_SERVICE_NAME,
        "deployment.environment": settings.ENVIRONMENT,
    })
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip("/")

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
    )
    set_logger_provider(logger_provider)

    HTTPXClientInstrumentor().instrument()


def instrument_fastapi(app: FastAPI) -> None:
    if not _otel_enabled():
        return
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")


def otel_loguru_handler() -> "HandlerConfig | None":
    if not _otel_enabled():
        return None
    return {
        "sink": LoggingHandler(logging.NOTSET),
        "level": settings.OTEL_LOG_LEVEL,
        "format": "{message}",
    }
