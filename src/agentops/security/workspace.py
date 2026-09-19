"""Repository sandboxing: agenten må kun læse/skrive inden for én konfigureret rod.

Trussel: en LLM-drevet agent kan blive instrueret (direkte af brugeren eller via
prompt injection i repository-indhold) til at anmode om stier som `../../etc/passwd`
eller absolutte stier uden for workspacet. `WorkspaceSandbox` er den ene
kontrollerede indgang, som validerer alle stier, før noget rører filsystemet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentops.security.exceptions import PathSecurityError

# Directories der aldrig skal kunne læses eller listes, selv inden for workspacet.
DENYLISTED_DIR_NAMES = {".git", ".env", "__pycache__", ".venv", "node_modules"}

MAX_READABLE_FILE_BYTES = 512_000


@dataclass(frozen=True)
class WorkspaceSandbox:
    """Validerer og løser stier relativt til en fast repository-rod."""

    root: Path

    def __post_init__(self) -> None:
        resolved = self.root.resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise PathSecurityError(
                f"Workspace root findes ikke eller er ikke en mappe: {resolved}"
            )
        object.__setattr__(self, "root", resolved)

    def resolve(self, relative_path: str, *, must_exist: bool = True) -> Path:
        """Løser en brugerangivet sti til en absolut sti inden for workspacet.

        Rejser PathSecurityError hvis stien (efter opløsning af `..` og symlinks)
        ville ligge uden for `self.root`, eller hvis den rammer en denylisted
        directory (fx `.git`, som kan indeholde credentials/hooks).
        """
        if relative_path.strip() == "":
            raise PathSecurityError("Tom sti er ikke tilladt.")

        candidate = (self.root / relative_path).resolve()

        if not self._is_within_root(candidate):
            raise PathSecurityError(f"Sti '{relative_path}' ligger uden for workspace-sandboxen.")

        for part in candidate.relative_to(self.root).parts:
            if part in DENYLISTED_DIR_NAMES:
                raise PathSecurityError(f"Adgang til '{part}' er ikke tilladt.")

        if must_exist and not candidate.exists():
            raise PathSecurityError(f"Sti '{relative_path}' findes ikke i workspacet.")

        return candidate

    def _is_within_root(self, candidate: Path) -> bool:
        try:
            return candidate.is_relative_to(self.root)
        except ValueError:
            return False

    def read_text(self, relative_path: str, max_bytes: int = MAX_READABLE_FILE_BYTES) -> str:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise PathSecurityError(f"'{relative_path}' er ikke en fil.")
        size = path.stat().st_size
        if size > max_bytes:
            raise PathSecurityError(
                f"Filen '{relative_path}' er {size} bytes, hvilket overskrider grænsen på {max_bytes}."
            )
        return path.read_text(encoding="utf-8", errors="replace")

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.resolve(relative_path, must_exist=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def to_relative(self, absolute_path: Path) -> str:
        return str(absolute_path.resolve().relative_to(self.root))
