from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import time

from .domain import Run
from .patching import validate_patch
from .policy import PolicyEngine


@dataclass(frozen=True)
class ReviewResult:
    passed: bool
    summary: str
    command_results: tuple[dict, ...]


class Reviewer:
    def __init__(self, policy: PolicyEngine):
        self.policy = policy

    def review(self, run: Run, workspace: Path, patch: str) -> ReviewResult:
        paths, _ = validate_patch(run, patch, self.policy)
        if not run.allowed_commands:
            return ReviewResult(False, f"Review FAIL: brak zatwierdzonych komend weryfikacyjnych; paths={paths}", ())
        results = []
        for argv in run.allowed_commands:
            self.policy.validate_command(run, argv)
            started = time.monotonic()
            env = {"PATH": os.getenv("PATH", ""), "HOME": str(workspace), "CI": "1", "PYTHONUNBUFFERED": "1"}
            try:
                p = subprocess.run(argv, cwd=workspace, env=env, capture_output=True, text=True, timeout=300, shell=False)
                out = (p.stdout + "\n" + p.stderr)[-12000:]
                results.append({"argv": argv, "returncode": p.returncode, "seconds": round(time.monotonic() - started, 3), "output": out})
            except subprocess.TimeoutExpired:
                results.append({"argv": argv, "returncode": 124, "seconds": 300, "output": "TIMEOUT"})
        failed = [x for x in results if x["returncode"] != 0]
        if failed:
            return ReviewResult(False, f"Review FAIL: {len(failed)} komend nie przeszło; paths={paths}", tuple(results))
        return ReviewResult(True, f"Review PASS: diff w scope, {len(results)} zatwierdzonych komend PASS; paths={paths}", tuple(results))
