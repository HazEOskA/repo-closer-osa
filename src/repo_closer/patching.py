from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .canonical import sha256_hex
from .domain import Run
from .policy import PolicyEngine, PolicyViolation

_DIFF_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def patch_paths(patch: str) -> list[str]:
    paths = []
    for a, b in _DIFF_RE.findall(patch):
        if a != b and a != "/dev/null" and b != "/dev/null":
            raise PolicyViolation("Rename/move nie jest dozwolony w MVP.")
        candidate = b if b != "/dev/null" else a
        paths.append(candidate)
    if not paths:
        raise PolicyViolation("Brak poprawnego unified diff.")
    return sorted(set(paths))


def validate_patch(run: Run, patch: str, policy: PolicyEngine, max_bytes: int = 250_000) -> tuple[list[str], str]:
    patch = strip_code_fence(patch)
    if len(patch.encode()) > max_bytes:
        raise PolicyViolation("Patch przekracza limit rozmiaru.")
    if "GIT binary patch" in patch or "new file mode 120000" in patch:
        raise PolicyViolation("Binary patch/symlink jest niedozwolony.")
    paths = [policy.validate_path(run, p) for p in patch_paths(patch)]
    return paths, sha256_hex(patch)


def apply_patch(workspace: Path, patch: str) -> None:
    patch_file = workspace / ".repo-closer.patch"
    patch_file.write_text(strip_code_fence(patch) + "\n", encoding="utf-8")
    try:
        subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=workspace, check=True, capture_output=True, text=True, timeout=30)
        subprocess.run(["git", "apply", "--whitespace=fix", str(patch_file)], cwd=workspace, check=True, capture_output=True, text=True, timeout=30)
    finally:
        patch_file.unlink(missing_ok=True)
