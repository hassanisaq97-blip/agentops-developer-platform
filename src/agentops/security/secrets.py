"""Redaction af secrets, før data rammer logs, MLflow traces eller API-responses.

Trussel: tool-arguments, environment-snapshots eller fil-indhold kan indeholde
API-nøgler eller adgangskoder. Denne redaction er defense-in-depth — den
primære kontrol er, at secrets kun læses fra environment variables og aldrig
sendes til agenten/modellen som en del af context.
"""

from __future__ import annotations

import re

_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|access[_-]?key)", re.IGNORECASE
)

_SECRET_VALUE_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI/Anthropic-style keys
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub personal access token
]

REDACTED = "***REDACTED***"


def redact_text(text: str) -> str:
    """Erstatter genkendelige secret-mønstre i fri tekst."""
    result = text
    for pattern in _SECRET_VALUE_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def redact_mapping(data: dict) -> dict:
    """Returnerer en kopi af `data`, hvor secret-agtige nøgler og værdier er redacted.

    Bruges før tool-arguments/results logges til structlog eller MLflow.
    """
    redacted: dict = {}
    for key, value in data.items():
        if _SECRET_KEY_PATTERN.search(key):
            redacted[key] = REDACTED
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_mapping(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            redacted[key] = value
    return redacted
