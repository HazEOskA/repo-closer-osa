from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from .domain import Run


class PolicyViolation(ValueError):
    pass


class PolicyEngine:
    def require_capability(self, run: Run, capability: str) -> None:
        if capability not in set(run.capabilities):
            raise PolicyViolation(f"Brak capability: {capability}")

    def validate_path(self, run: Run, path: str) -> str:
        p = path.replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        pure = PurePosixPath(p)
        if not p or pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
            raise PolicyViolation(f"Niedozwolona ścieżka: {path}")
        for denied in run.denied_paths:
            if fnmatch(p, denied) or p == denied or p.startswith(denied.rstrip("/") + "/"):
                raise PolicyViolation(f"Ścieżka poza polityką: {p}")
        if run.allowed_files and not any(fnmatch(p, allowed) for allowed in run.allowed_files):
            raise PolicyViolation(f"Ścieżka poza zatwierdzonym scope: {p}")
        return p

    def validate_command(self, run: Run, argv: list[str]) -> None:
        if not argv:
            raise PolicyViolation("Pusta komenda.")
        if not any(argv == allowed for allowed in run.allowed_commands):
            raise PolicyViolation(f"Komenda niezatwierdzona: {argv!r}")
