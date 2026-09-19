"""Allowlist af repositories, agenten må arbejde i via API'et.

Trust boundary: en API-klient må ALDRIG kunne sende en vilkårlig filsti og få
agenten til at operere der — det ville underminere hele sandbox-modellen i
agentops.security.workspace. I stedet vælger klienten et navn fra en
serverkonfigureret allowlist. Se docs/security.md.
"""

from __future__ import annotations

from pathlib import Path

from agentops.settings import Settings


class UnknownRepositoryError(Exception):
    pass


def allowed_repositories(settings: Settings) -> dict[str, Path]:
    return {"demo": settings.workspace_root}


def resolve_repository(name: str, settings: Settings) -> Path:
    repos = allowed_repositories(settings)
    if name not in repos:
        raise UnknownRepositoryError(
            f"Repository '{name}' er ikke på allowlisten. Tilladt: {sorted(repos)}"
        )
    return repos[name]
