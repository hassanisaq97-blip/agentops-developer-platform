"""Beskytter mod, at skadeligt/prompt-injected indhold gemmes som tillid værdig memory.

Trussel: memory-udtræk kan indirekte indeholde tekst påvirket af et repositorys
fil-indhold (fx via `AgentRunResult.final_answer`, hvis en RIGTIG model blev
manipuleret af injiceret tekst i en fil den læste — se
evals/fixtures/prompt_injection_in_file_content/). Uden denne kontrol ville en
efterfølgende opgave kunne "arve" et injiceret forsøg som om det var en
legitim, tillid værdig erfaring fra en tidligere kørsel — et forgiftet
memory-lag er potentielt værre end selve injektionen, fordi det ser
autoritativt ud næste gang.

Denne sanitizer er defense-in-depth: den primære kontrol er stadig, at kun
STRUKTUREREDE felter fra `AgentRunResult` (aldrig rå tool-result-tekst)
bliver til memory-kandidater — se `agentops.memory.extraction`.
"""

from __future__ import annotations

import re

MAX_MEMORY_TEXT_LENGTH = 500

REDACTED_PLACEHOLDER = "[REDACTED: muligt forsøg på prompt injection i kildeindhold]"

_INJECTION_MARKERS = [
    re.compile(r"ignorer\s+(alle\s+)?(tidligere\s+)?instruktion", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?(previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"system\s*[-_ ]?\s*override", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bdu\s+er\s+nu\b", re.IGNORECASE),
    re.compile(r"ny\s+opgave\s+er\s+ikke", re.IGNORECASE),
]


def sanitize_memory_text(
    text: str, *, max_length: int = MAX_MEMORY_TEXT_LENGTH
) -> tuple[str, bool]:
    """Renser og trunkerer `text`, og flagger den hvis den ligner et injection-forsøg.

    Returnerer (tekst, flagged). Når flagged=True er den returnerede tekst en
    fast placeholder — det oprindelige (mistænkelige) indhold gemmes ALDRIG,
    hverken saniteret eller rå.
    """
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    truncated = cleaned.strip()[:max_length]
    if any(pattern.search(truncated) for pattern in _INJECTION_MARKERS):
        return REDACTED_PLACEHOLDER, True
    return truncated, False
