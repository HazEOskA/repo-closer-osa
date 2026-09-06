from __future__ import annotations

import base64
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GitHubReadClient:
    """Celowo tylko GET. Slice 1 nie posiada metod write."""

    api_base = "https://api.github.com"

    def __init__(self, token: str | None = None, timeout: int = 20):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.timeout = timeout

    def _get(self, path: str):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "osa-repo-closer/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(f"{self.api_base}{path}", headers=headers, method="GET")
        try:
            with urlopen(req, timeout=self.timeout) as res:
                return json.loads(res.read().decode())
        except HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"GitHub GET {exc.code}: {body[:400]}") from exc

    def repo_meta(self, owner: str, repo: str):
        return self._get(f"/repos/{quote(owner)}/{quote(repo)}")

    def commit(self, owner: str, repo: str, ref: str):
        return self._get(f"/repos/{quote(owner)}/{quote(repo)}/commits/{quote(ref, safe='')}")

    def tree(self, owner: str, repo: str, tree_sha: str):
        return self._get(f"/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(tree_sha, safe='')}?recursive=1")

    def file_text(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        data = self._get(f"/repos/{quote(owner)}/{quote(repo)}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}")
        if not isinstance(data, dict) or data.get("type") != "file":
            return None
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]).decode(errors="replace")
        return None
