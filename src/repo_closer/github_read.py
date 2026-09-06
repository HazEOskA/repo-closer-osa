from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass
class GitHubReadError(RuntimeError):
    status: int
    message: str

    def __str__(self) -> str:
        return f"GitHub GET failed ({self.status}): {self.message}"


class GitHubReadClient:
    """Read-only GitHub adapter. Intentionally exposes GET operations only."""

    api_base = "https://api.github.com"

    def __init__(self, token: str | None = None, timeout: int = 20):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.timeout = timeout

    def _get(self, path: str) -> Any:
        url = f"{self.api_base}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "osa-repo-closer/0.2",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GitHubReadError(exc.code, body[:500]) from exc
        return json.loads(raw.decode("utf-8"))

    def repo_meta(self, owner: str, repo: str) -> dict[str, Any]:
        return self._get(f"/repos/{quote(owner)}/{quote(repo)}")

    def commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        return self._get(f"/repos/{quote(owner)}/{quote(repo)}/commits/{quote(ref, safe='')}")

    def tree(self, owner: str, repo: str, tree_sha: str) -> dict[str, Any]:
        return self._get(f"/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(tree_sha, safe='')}?recursive=1")

    def file_text(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        data = self._get(f"/repos/{quote(owner)}/{quote(repo)}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}")
        if not isinstance(data, dict) or data.get("type") != "file":
            return None
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return None
