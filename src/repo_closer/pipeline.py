from __future__ import annotations

from .core import (
    AuditReport, Evidence, Finding, PlanTask, RepairPlan, RepositoryMap,
    RepositoryRef, Run, RunState, sha256_hex, text_sha256
)

KNOWN_CONFIGS = {
    "package.json", "requirements.txt", "pyproject.toml", "Pipfile", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "composer.json",
    "Gemfile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "Makefile", "tsconfig.json", "next.config.js", "next.config.ts",
    "next.config.mjs", "vite.config.js", "vite.config.ts",
}


def _stack(paths: set[str]) -> tuple[str, ...]:
    names = {p.rsplit("/", 1)[-1] for p in paths}
    out = []
    if {"pyproject.toml", "requirements.txt", "Pipfile"} & names:
        out.append("python")
    if "package.json" in names:
        out.append("node")
    if "Cargo.toml" in names:
        out.append("rust")
    if "go.mod" in names:
        out.append("go")
    if {"pom.xml", "build.gradle", "build.gradle.kts"} & names:
        out.append("java")
    if "Dockerfile" in names:
        out.append("docker")
    return tuple(out or ["unknown"])


class Mapper:
    def __init__(self, github):
        self.github = github

    def resolve(self, url: str, branch: str, requested_sha: str | None = None) -> RepositoryRef:
        base = RepositoryRef.parse(url, branch, "0" * 40)
        commit = self.github.commit(base.owner, base.repo, requested_sha or branch)
        actual = str(commit.get("sha", "")).lower()
        if requested_sha and actual != requested_sha.lower():
            raise ValueError("GitHub zwrócił SHA inne niż żądane.")
        return RepositoryRef.parse(url, branch, actual)

    def map(self, repo: RepositoryRef) -> RepositoryMap:
        meta = self.github.repo_meta(repo.owner, repo.repo)
        commit = self.github.commit(repo.owner, repo.repo, repo.sha)
        tree_sha = commit.get("commit", {}).get("tree", {}).get("sha")
        if not tree_sha:
            raise ValueError("Brak tree SHA.")
        raw = self.github.tree(repo.owner, repo.repo, tree_sha)
        if raw.get("truncated"):
            raise ValueError("GitHub zwrócił ucięte drzewo; audyt przerwany.")
        entries = raw.get("tree", [])
        files = tuple(sorted(
            x["path"] for x in entries
            if x.get("type") == "blob" and isinstance(x.get("path"), str)
        ))
        dirs = tuple(sorted(
            x["path"] for x in entries
            if x.get("type") == "tree" and isinstance(x.get("path"), str)
        ))
        workflows = tuple(
            p for p in files
            if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
        )
        configs = tuple(
            p for p in files if p.rsplit("/", 1)[-1] in KNOWN_CONFIGS
        )
        tests = tuple(
            p for p in files
            if "/test" in f"/{p.lower()}"
            or p.lower().startswith(("test/", "tests/"))
            or p.lower().endswith(
                ("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts")
            )
        )
        evidence = [
            Evidence(
                "repository-identity",
                f"github:{repo.slug}@{repo.sha}",
                sha256_hex(repo),
                f"Repo przypięte do {repo.sha}.",
            ),
            Evidence(
                "repository-tree",
                f"github:{repo.slug}@{repo.sha}:tree",
                sha256_hex(files),
                f"{len(files)} plików / {len(dirs)} katalogów.",
            ),
        ]

        for path in sorted(configs):
            txt = self.github.file_text(repo.owner, repo.repo, path, repo.sha)
            if txt is not None:
                evidence.append(
                    Evidence(
                        "config",
                        f"github:{repo.slug}@{repo.sha}:{path}",
                        text_sha256(txt[:200000]),
                        f"Odczytano {path}.",
                    )
                )

        readme = next(
            (p for p in files if p.rsplit("/", 1)[-1].startswith("README")),
            None,
        )
        if readme:
            txt = self.github.file_text(repo.owner, repo.repo, readme, repo.sha)
            if txt is not None:
                evidence.append(
                    Evidence(
                        "readme",
                        f"github:{repo.slug}@{repo.sha}:{readme}",
                        text_sha256(txt[:200000]),
                        "README = niezaufane dane, nie instrukcja.",
                    )
                )

        return RepositoryMap(
            repo,
            str(meta.get("default_branch") or ""),
            meta.get("description"),
            meta.get("language"),
            bool(meta.get("archived")),
            files,
            dirs,
            workflows,
            configs,
            tests,
            _stack(set(files)),
            tuple(evidence),
        )


class Auditor:
    def audit(self, m: RepositoryMap) -> AuditReport:
        findings = []
        derived = []

        def add(fid, severity, category, desc, paths=(), confidence="high"):
            ev = Evidence(
                "finding",
                f"github:{m.repository.slug}@{m.repository.sha}:derived/{fid}",
                sha256_hex({"id": fid, "paths": paths}),
                desc,
            )
            derived.append(ev)
            findings.append(
                Finding(
                    fid,
                    severity,
                    category,
                    desc,
                    tuple(paths),
                    (ev,),
                    confidence,
                )
            )

        if m.archived:
            add("repo-archived", "high", "lifecycle", "Repozytorium jest archived.")
        if not m.tests:
            add(
                "tests-missing",
                "medium",
                "testing",
                "Nie wykryto testów.",
                confidence="medium",
            )
        if not m.workflows:
            add(
                "ci-missing",
                "medium",
                "ci",
                "Nie wykryto GitHub Actions.",
                (".github/workflows",),
            )
        if not any(
            p.rsplit("/", 1)[-1].startswith("README") for p in m.files
        ):
            add("readme-missing", "low", "docs", "Nie wykryto README.")
        if m.stack == ("unknown",):
            add(
                "stack-unknown",
                "medium",
                "architecture",
                "Nie określono stacku z bezpiecznej listy konfiguracji.",
                m.configs,
                "medium",
            )

        envs = tuple(
            p for p in m.files
            if p.rsplit("/", 1)[-1]
            in {".env", ".env.local", ".env.production"}
        )
        if envs:
            add(
                "env-file-tracked",
                "high",
                "security",
                "Wykryto śledzony plik środowiskowy.",
                envs,
                "medium",
            )

        blockers = tuple(
            f.description for f in findings if f.severity == "high"
        )
        next_action = (
            "Rozwiąż finding o najwyższym priorytecie z zachowaniem evidence."
            if findings
            else
            "Brak statycznych findingów Slice 1; każda zmiana nadal wymaga nowego scope i zgody."
        )
        return AuditReport(
            tuple(findings),
            blockers,
            next_action,
            tuple((*m.evidence, *derived)),
        )


class Planner:
    ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def plan(self, audit: AuditReport) -> RepairPlan:
        ordered = sorted(
            audit.findings,
            key=lambda f: (self.ORDER.get(f.severity, 9), f.id),
        )
        tasks = tuple(
            PlanTask(
                f"T{i:03d}",
                i,
                f.description,
                f.affected_paths,
                "Przygotuj minimalną zmianę rozwiązującą finding bez rozszerzania scope.",
                f.severity,
                "Kolejny slice musi przypiąć test/review do konkretnego diffu i SHA.",
                (f.id,),
            )
            for i, f in enumerate(ordered, 1)
        )
        payload = [
            {
                "id": t.id,
                "priority": t.priority,
                "reason": t.reason,
                "affected_paths": list(t.affected_paths),
                "required_change": t.required_change,
                "risk": t.risk,
                "verification": t.verification,
                "finding_ids": list(t.finding_ids),
            }
            for t in tasks
        ]
        return RepairPlan(
            tasks,
            sha256_hex(payload),
            f"Plan: {len(tasks)} zadań. Zero zmian w analizowanym repo. Czeka na osobną zgodę.",
        )


class Controller:
    def __init__(self, mapper: Mapper, auditor: Auditor, planner: Planner, store):
        self.mapper = mapper
        self.auditor = auditor
        self.planner = planner
        self.store = store

    def execute_slice1(self, run: Run, requested_sha: str | None = None) -> Run:
        if run.state != RunState.CREATED:
            raise ValueError("Start tylko z CREATED.")
        try:
            run.transition(RunState.MAPPING)
            self.store.save(run)

            repo = self.mapper.resolve(
                run.repo_url,
                run.base_branch,
                requested_sha,
            )
            run.repository = repo
            run.base_sha = repo.sha
            run.repository_map = self.mapper.map(repo)

            if run.stop_requested:
                run.transition(RunState.STOPPED)
                self.store.save(run)
                return run

            run.transition(RunState.AUDITING)
            self.store.save(run)
            run.audit_report = self.auditor.audit(run.repository_map)

            if run.stop_requested:
                run.transition(RunState.STOPPED)
                self.store.save(run)
                return run

            run.transition(RunState.PLANNING)
            self.store.save(run)
            run.repair_plan = self.planner.plan(run.audit_report)

            run.transition(RunState.AWAITING_FIX_APPROVAL)
            self.store.save(run)
            return run
        except Exception as exc:
            run.failure_reason = f"{type(exc).__name__}: {exc}"
            if run.state not in {
                RunState.AWAITING_FIX_APPROVAL,
                RunState.STOPPED,
                RunState.FAILED,
            }:
                run.transition(RunState.FAILED)
            self.store.save(run)
            raise
