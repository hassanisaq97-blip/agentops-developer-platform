"""Deterministisk, statisk sikkerhedsscanning af en git diff.

Bruges af Security Agent-fasen i `agentops.agent.multi_agent` — bevidst IKKE
et LLM-kald: den deterministiske test-provider har ingen reel evne til at
vurdere sikkerhed semantisk (den reagerer kun på strukturerede
tool-resultater, se docs/experiments/lessons-learned.md), så en "AI-drevet
sikkerhedsreview" ville enten være meningsløs med test-provideren eller
umulig at måle ærligt. En simpel, mønster-baseret statisk scanning er derimod
ægte, deterministisk og provider-uafhængig — den samme kontrol kører uanset
om Developer Agent-fasen blev drevet af en rigtig model eller test-provideren.
"""

from __future__ import annotations

import re

from agentops.security.secrets import redact_text

_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\beval\("), "Brug af eval() — kan udføre vilkårlig kode."),
    (re.compile(r"\bexec\("), "Brug af exec() — kan udføre vilkårlig kode."),
    (re.compile(r"os\.system\("), "Brug af os.system() — command injection-risiko."),
    (
        re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"),
        "subprocess-kald med shell=True — command injection-risiko.",
    ),
    (re.compile(r"pickle\.loads?\("), "Brug af pickle — usikker deserialisering."),
    (re.compile(r"\.\./"), "Muligt path traversal-mønster ('../') i den ændrede kode."),
]


def scan_diff_for_issues(diff_text: str) -> list[str]:
    """Scanner kun TILFØJEDE linjer (`+`) i en unified diff — vi vurderer den NYE
    kode, ikke kontekstlinjer eller fjernet kode."""
    findings: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        for pattern, message in _DANGEROUS_PATTERNS:
            if pattern.search(added) and message not in findings:
                findings.append(message)
        if redact_text(added) != added:
            secret_message = "Muligt hardkodet secret fundet i den ændrede kode."
            if secret_message not in findings:
                findings.append(secret_message)
    return findings
