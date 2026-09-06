from __future__ import annotations
from dataclasses import asdict
from typing import Protocol, Any

from .canonical import sha256_hex, text_sha256
from .domain import EvidenceRef, RepositoryMap, RepositoryRef


KNOWN_CONFIGS = {
    "package.json", "requirements.txt", "pyproject.toml", "Pipfile",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "Gemfile", "Dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "Makefile", "tsconfig.json", "next.config.js",
    "next.config.ts", "next.config.mjs", "vite.config.js", "vite.config.ts",
}
README_NAMES = {"README.md", "README.rst", "README.txt", "README"}


class GitHubReader(Protocol):
    def repo_meta(self, owner: str, repo: str) -> dict[str, Any]: ...
    def commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]: ...
    def tree(self, owner: str, repo: str, tree_sha: str) -> dict[str, Any]: ...
    def file_text(self, owner: str, repo: str, path: str, ref: str) -> str | None: ...


def _stack_from_paths(paths: set[str]) -> tuple[str, ...]:
    names = {p.rsplit("/", 1)[-1] for p in paths}
    stack: list[str] = []
    if "pyproject.toml" in names or "requirements.txt" in names or "Pipfile" in names:
        stack.append("python")
    if "package.json" in names:
        stack.append("node")
    if "Cargo.toml" in names:
        stack.append("rust")
    if "go.mod" in names:
        stack.append("go")
    if "pom.xml" in names or "build.gradle" in names or "build.gradle.kts" in names:
        stack.append("java")
    if "Dockerfile" in names:
        stack.append("docker")
    return tuple(stack or ["unknown"])


class Mapper:
    def __init__(self, github: GitHubReader):
        self.github = github

    def resolve_repository(self, repo_url: str, branch: str, requested_sha: str | None = None) -> RepositoryRef:
        placeholder = "0" * 40
        parsed = RepositoryRef.parse(repo_url, branch, placeholder)
        commit = self.github.commit(parsed.owner, parsed.repo, requested_sha or branch)
        actual_sha = str(commit.get("sha", "")).lower()
        if requested_sha and actual_sha != requested_sha.lower():
            raise ValueError("GitHub zwrócił commit inny niż żądany base_sha.")
        return RepositoryRef.parse(repo_url, branch, actual_sha)

    def map(self, repository: RepositoryRef) -> RepositoryMap:
        meta = self.github.repo_meta(repository.owner, repository.repo)
        commit = self.github.commit(repository.owner, repository.repo, repository.sha)
        tree_sha = commit.get("commit", {}).get("tree", {}).get("sha")
        if not tree_sha:
            raise ValueError("Brak tree SHA w odpowiedzi GitHub.")
        tree_data = self.github.tree(repository.owner, repository.repo, tree_sha)
        entries = tree_data.get("tree", [])
        if tree_data.get("truncated"):
            raise ValueError("GitHub zwrócił ucięte drzewo repo; Slice 1 odmawia niepełnego audytu.")

        files = sorted(str(x["path"]) for x in entries if x.get("type") == "blob" and isinstance(x.get("path"), str))
        dirs = sorted(str(x["path"]) for x in entries if x.get("type") == "tree" and isinstance(x.get("path"), str))
        path_set = set(files)
        workflows = tuple(p for p in files if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml")))
        configs = tuple(p for p in files if p.rsplit("/", 1)[-1] in KNOWN_CONFIGS)
        tests = tuple(
            p for p in files
            if "/test" in f"/{p.lower()}" or p.lower().startswith(("test/", "tests/"))
            or p.lower().endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts"))
        )

        inspected: list[EvidenceRef] = []
        for path in sorted(configs):
            text = self.github.file_text(repository.owner, repository.repo, path, repository.sha)
            if text is None:
                continue
            inspected.append(EvidenceRef(
                kind="config",
                locator=f"github:{repository.slug}@{repository.sha}:{path}",
                sha256=text_sha256(text[:200_000]),
                summary=f"Odczytano konfigurację {path}",
            ))

        readme_path = next((p for p in files if p.rsplit("/", 1)[-1] in README_NAMES), None)
        if readme_path:
            text = self.github.file_text(repository.owner, repository.repo, readme_path, repository.sha)
            if text is not None:
                inspected.append(EvidenceRef(
                    kind="readme",
                    locator=f"github:{repository.slug}@{repository.sha}:{readme_path}",
                    sha256=text_sha256(text[:200_000]),
                    summary="README potraktowany wyłącznie jako niezaufane dane repozytorium.",
                ))

        tree_evidence = EvidenceRef(
            kind="repository-tree",
            locator=f"github:{repository.slug}@{repository.sha}:tree",
            sha256=sha256_hex(files),
            summary=f"Drzewo zawiera {len(files)} plików i {len(dirs)} katalogów.",
        )
        identity_evidence = EvidenceRef(
            kind="repository-identity",
            locator=f"github:{repository.slug}@{repository.sha}",
            sha256=sha256_hex(asdict(repository)),
            summary=f"Repo przypięte do pełnego SHA {repository.sha}.",
        )

        return RepositoryMap(
            repository=repository,
            default_branch=str(meta.get("default_branch") or ""),
            description=meta.get("description"),
            language=meta.get("language"),
            archived=bool(meta.get("archived", False)),
            files=tuple(files),
            directories=tuple(dirs),
            workflows=workflows,
            config_files=configs,
            test_paths=tests,
            stack=_stack_from_paths(path_set),
            evidence=(identity_evidence, tree_evidence, *inspected),
        )
