"""Struktureret logging (JSON) med automatisk secret-redaction.

Al logging i platformen — både stdlib `logging` (brugt i gateway/orchestrator
for simple advarsler) og `structlog` (brugt i API-laget for request-logs) —
render's som JSON gennem denne ene konfiguration, så logs kan indekseres af
et log-aggregeringsværktøj i produktion. `_redact_event` sikrer, at et
tool-argument eller en fejlbesked, der ved et uheld indeholder en nøgle,
aldrig ender i logs — se agentops.security.secrets for mønstrene.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from agentops.security.secrets import redact_mapping


def _redact_event(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    return redact_mapping(dict(event_dict))


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_event,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(numeric_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
