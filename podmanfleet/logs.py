import logging
from typing import TYPE_CHECKING

import sentry_sdk
import yaml
from loguru import logger
from rich.logging import RichHandler
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

if TYPE_CHECKING:
    from loguru import HandlerConfig, Record

from podmanfleet.config import settings
from podmanfleet.tracing import otel_loguru_handler, setup_otel


def setup_logging():
    setup_otel()
    _setup_logger()
    _setup_sentry()


def _setup_logger():
    logger.remove()

    rich_handler = RichHandler(rich_tracebacks=True, log_time_format="%X", markup=True)

    def _format_with_extra(record: "Record") -> str:
        message = record["message"]

        if record["extra"]:
            extra = yaml.dump(record["extra"], sort_keys=False, default_flow_style=False)
            message = f"{message}\n{extra}"

        return message.replace("[", r"\[").replace("{", "{{").replace("}", "}}").replace("<", r"\<")

    handlers: list[HandlerConfig] = [
        {
            "sink": rich_handler,
            "format": _format_with_extra,
            "level": settings.OTEL_LOG_LEVEL,
            "backtrace": True,
            "diagnose": True,
        }
    ]

    otel_handler = otel_loguru_handler()
    if otel_handler is not None:
        handlers.append(otel_handler)

    logger.configure(handlers=handlers)

    # Override the loggers of external libraries to ensure consistent formatting
    for logger_name in (
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
    ):
        lib_logger = logging.getLogger(logger_name)
        lib_logger.handlers.clear()  # Remove existing handlers
        lib_logger.addHandler(rich_handler)
        lib_logger.propagate = False


def _setup_sentry():
    if not settings.SENTRY_DSN:
        logger.warning("Sentry is disabled, no SENTRY_DSN provided")
        return

    logger.info("Initializing Sentry")
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        integrations=[
            StarletteIntegration(
                transaction_style="endpoint",
                failed_request_status_codes={403, *range(500, 599)},
            ),
            FastApiIntegration(
                transaction_style="endpoint",
                failed_request_status_codes={403, *range(500, 599)},
            ),
            LoggingIntegration(level=logging.getLevelNamesMapping()[settings.OTEL_LOG_LEVEL]),
        ],
        send_default_pii=True,
    )
