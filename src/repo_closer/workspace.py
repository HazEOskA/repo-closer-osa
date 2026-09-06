from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote

from .domain import RepositoryRef


class WorkspaceManager:
    def __init__(self, root: str | None = None):
        self.root = Path(root or os.getenv("MAINTENANCE_WORKSPACE_ROOT", "/tmp/repo-closer"))
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, repository: RepositoryRef, run_id: str, github_token: str | None = None) -> Path:
        target = Path(tempfile.mkdtemp(prefix=f"{run_id[:8]}-", dir=self.root))
        url = repository.url + ".git"
        if github_token:
            url = f"https://x-access-token:{quote(github_token, safe='')}@github.com/{repository.owner}/{repository.repo}.git"
        subprocess.run(["git", "clone", "--no-checkout", "--filter=blob:none", url, str(target)], check=True, capture_output=True, text=True, timeout=180)
        subprocess.run(["git", "checkout", "--detach", repository.sha], cwd=target, check=True, capture_output=True, text=True, timeout=60)
        return target

    def cleanup(self, path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)
