from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .domain import RepositoryRef


class GitHubWriteClient:
    def __init__(self, token: str | None = None, timeout: int = 30):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.timeout = timeout
        if not self.token:
            raise RuntimeError("Brak GITHUB_TOKEN dla operacji write.")

    def _request(self, method: str, path: str, payload: dict | None = None):
        body = None if payload is None else json.dumps(payload).encode()
        req = Request(
            f"https://api.github.com{path}", body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "osa-repo-closer/0.2",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            }, method=method,
        )
        try:
            with urlopen(req, timeout=self.timeout) as res:
                return json.loads(res.read().decode()) if res.length != 0 else {}
        except HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"GitHub {method} {exc.code}: {body[:800]}") from exc

    def publish_branch(self, repository: RepositoryRef, workspace: Path, branch: str, message: str) -> str:
        subprocess.run(["git", "config", "user.name", "OSA Repo Closer"], cwd=workspace, check=True)
        subprocess.run(["git", "config", "user.email", "repo-closer@users.noreply.github.com"], cwd=workspace, check=True)
        subprocess.run(["git", "checkout", "-B", branch], cwd=workspace, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=workspace, check=True, capture_output=True, text=True)
        remote = f"https://x-access-token:{quote(self.token, safe='')}@github.com/{repository.owner}/{repository.repo}.git"
        subprocess.run(["git", "push", remote, f"HEAD:refs/heads/{branch}", "--force-with-lease"], cwd=workspace, check=True, capture_output=True, text=True, timeout=180)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace, text=True).strip()

    def create_pr(self, repository: RepositoryRef, branch: str, title: str, body: str) -> str:
        data = self._request("POST", f"/repos/{repository.owner}/{repository.repo}/pulls", {"title": title, "head": branch, "base": repository.branch, "body": body, "draft": False})
        return data["html_url"]
