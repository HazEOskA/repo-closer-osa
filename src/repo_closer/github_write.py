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

    def create_pr(self, repository: RepositoryRef, branch: str, title: str, body: str) -> tuple[str, int]:
        data = self._request("POST", f"/repos/{repository.owner}/{repository.repo}/pulls", {
            "title": title,
            "head": branch,
            "base": repository.branch,
            "body": body,
            "draft": False,
        })
        return str(data["html_url"]), int(data["number"])

    def require_successful_checks(self, repository: RepositoryRef, head_sha: str) -> tuple[tuple[str, str], ...]:
        data = self._request(
            "GET",
            f"/repos/{repository.owner}/{repository.repo}/commits/{head_sha}/check-runs?per_page=100",
        )
        runs = list(data.get("check_runs") or [])
        if not runs:
            raise RuntimeError("Brak CI check-runs dla zatwierdzonego head SHA; merge pozostaje zablokowany.")

        normalized = tuple(
            (str(run.get("name") or "unnamed"), str(run.get("conclusion") or run.get("status") or "unknown"))
            for run in runs
        )
        unfinished = [name for name, _ in normalized if next(
            (x.get("status") for x in runs if str(x.get("name") or "unnamed") == name), None
        ) != "completed"]
        if unfinished:
            raise RuntimeError(f"CI jeszcze trwa dla head SHA: {unfinished}")

        accepted = {"success", "neutral", "skipped"}
        failed = [(name, conclusion) for name, conclusion in normalized if conclusion not in accepted]
        if failed:
            raise RuntimeError(f"CI nie jest green dla head SHA: {failed}")
        if not any(conclusion == "success" for _, conclusion in normalized):
            raise RuntimeError("CI nie zawiera ani jednego check-run zakończonego success.")
        return normalized

    def merge_pr(self, repository: RepositoryRef, pr_number: int, head_sha: str) -> str:
        pr = self._request("GET", f"/repos/{repository.owner}/{repository.repo}/pulls/{pr_number}")
        actual_head = str(pr.get("head", {}).get("sha") or "")
        actual_base = str(pr.get("base", {}).get("ref") or "")
        if actual_head != head_sha:
            raise RuntimeError(f"PR head drift: oczekiwano {head_sha}, GitHub zwrócił {actual_head}.")
        if actual_base != repository.branch:
            raise RuntimeError(f"PR base drift: oczekiwano {repository.branch}, GitHub zwrócił {actual_base}.")

        self.require_successful_checks(repository, head_sha)
        data = self._request(
            "PUT",
            f"/repos/{repository.owner}/{repository.repo}/pulls/{pr_number}/merge",
            {"sha": head_sha, "merge_method": "squash"},
        )
        if not data.get("merged"):
            raise RuntimeError(f"GitHub odmówił merge: {data.get('message', 'unknown reason')}")
        merge_sha = str(data.get("sha") or "")
        if len(merge_sha) != 40:
            raise RuntimeError("GitHub nie zwrócił pełnego merge SHA.")
        return merge_sha
