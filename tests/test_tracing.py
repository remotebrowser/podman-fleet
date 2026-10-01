"""`instrument_fastapi` must keep the ASGI instrumentor from starting a span per WebSocket
message: the CDP relay pushes every frame across the ASGI send/receive boundary, so those
per-message spans flood the OTLP endpoint with two spans per frame."""

import re
from typing import Any

import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from pytest import MonkeyPatch

from podmanfleet import tracing
from podmanfleet.config import settings

_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


@pytest.fixture
def instrumented_calls(monkeypatch: MonkeyPatch) -> list[dict[str, Any]]:
    """Record `FastAPIInstrumentor.instrument_app` calls instead of instrumenting for real."""
    calls: list[dict[str, Any]] = []

    class _SpyInstrumentor:
        @staticmethod
        def instrument_app(app: FastAPI, **kwargs: Any) -> None:
            calls.append({"app": app, **kwargs})

    monkeypatch.setattr(tracing, "FastAPIInstrumentor", _SpyInstrumentor)
    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.test")
    return calls


def test_skips_instrumentation_when_no_otlp_endpoint(
    monkeypatch: MonkeyPatch, instrumented_calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "")

    tracing.instrument_fastapi(FastAPI())

    assert instrumented_calls == []


def test_excludes_the_per_message_send_and_receive_spans(
    instrumented_calls: list[dict[str, Any]],
) -> None:
    app = FastAPI()

    tracing.instrument_fastapi(app)

    assert len(instrumented_calls) == 1
    assert instrumented_calls[0]["app"] is app
    assert instrumented_calls[0]["excluded_urls"] == "/health"
    assert instrumented_calls[0]["exclude_spans"] == ["send", "receive"]


def test_current_traceparent_empty_when_otel_disabled(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(tracing.settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "")
    assert tracing.current_traceparent() == ""


def test_current_traceparent_builds_w3c_string_for_active_span(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(tracing.settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

    tracer = TracerProvider().get_tracer(__name__)
    with tracer.start_as_current_span("test-span"):
        traceparent = tracing.current_traceparent()

    assert _TRACEPARENT_RE.match(traceparent)


def test_current_traceparent_empty_without_active_span(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(tracing.settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setattr(trace, "get_current_span", lambda context=None: trace.INVALID_SPAN)

    assert tracing.current_traceparent() == ""
