"""Indlæser applikationskonfiguration fra disk."""

from __future__ import annotations

import json
from pathlib import Path


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text())
