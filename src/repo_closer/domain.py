from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse
import re
import uuid

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class RunState(StrEnum):
    CREATED = "CREATED"
    MAPPING = "MAPPING"
    AUDITING = "AUDITING"
    PLANNING = "PLANNING"
    AWAITING_FIX_APPROVAL = "AWAITING_FIX_APPROVAL"
    FIXING = "FIXING"
    REVIEWING = "REVIEWING"
    AWAITING_PR_APPROVAL = "AWAITING_PR_APPROVAL"
    PUBLISHING_PR = "PUBLISHING_PR"
    PR_OPEN = "PR_OPEN"
    MERGING = "MERGING"
    MERGED = "MERGED"
    BUILDING = "BUILDING"
    AWAITING_DEPLOY_APPROVAL = "AWAITING_DEPLOY_APPROVAL"
    DEPLOYING = "DEPLOYING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    STOPPED = "STOPPED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    FAILED = "FAILED"


_TERMINAL = {
    RunState.COMPLETED,
    RunState.BLOCKED,
    RunState.STOPPED,
    RunState.BUDGET_EXCEEDED,
    RunState.FAILED,
}

_ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.MAPPING},
    RunState.MAPPING: {RunState.AUDITING},
    RunState.AUDITING: {RunState.PLANNING},
    RunState.PLANNING: {RunState.AWAITING_FIX_APPROVAL},
    RunState.AWAITING_FIX_APPROVAL: {RunState.FIXING},
    RunState.FIXING: {RunState.REVIEWING},
    RunState.REVIEWING: {RunState.FIXING, RunState.AWAITING_PR_APPROVAL},
    RunState.AWAITING_PR_APPROVAL: {RunState.PUBLISHING_PR},
    RunState.PUBLISHING_PR: {RunState.PR_OPEN},
    RunState.PR_OPEN: {RunState.MERGING, RunState.COMPLETED},
    RunState.MERGING: {RunState.MERGED},
    RunState.MERGED: {RunState.BUILDING, RunState.COMPLETED},
    RunState.BUILDING: {RunState.AWAITING_DEPLOY_APPROVAL},
    RunState.AWAITING_DEPLOY_APPROVAL: {RunState.DEPLOYING},
    RunState.DEPLOYING: {RunState.VERIFYING},
    RunState.VERIFYING: {RunState.FIXING, RunState.COMPLETED},
}
for _state in list(_ALLOWED_TRANSITIONS):
    if _state not in _TERMINAL:
        _ALLOWED_TRANSITIONS[_state] |= {
            RunState.BLOCKED,
            RunState.STOPPED,
            RunState.BUDGET_EXCEEDED,
            RunState.FAILED,
        }
for _state in _TERMINAL:
    _ALLOWED_TRANSITIONS.setdefault(_state, set())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RepositoryRef:
    url: str
    owner: str
    repo: str
    branch: str
    sha: str

    @classmethod
    def parse(cls, url: str, branch: str, sha: str) -> "RepositoryRef":
        parsed = urlparse(url.strip())
        if parsed.scheme != "https" or parsed.hostname != "github.com":
            raise ValueError("Obsługiwane są wyłącznie adresy https://github.com/OWNER/REPO.")
        parts = [p for p in parsed.path.removesuffix(".git").strip("/").split("/") if p]
        if len(parts) != 2:
            raise ValueError("URL musi wskazywać dokładnie root repozytorium GitHub.")
        owner, repo = parts
        if not _NAME_RE.fullmatch(owner) or not _NAME_RE.fullmatch(repo):
            raise ValueError("Nieprawidłowa nazwa właściciela lub repozytorium.")
        if not branch or any(x in branch for x in ("\x00", "\n", "\r")):
            raise ValueError("Nieprawidłowa nazwa brancha.")
        sha = sha.lower()
        if not _SHA_RE.fullmatch(sha):
            raise ValueError("SHA musi być pełnym 40-znakowym SHA-1 w hex.")
        return cls(
            url=f"https://github.com/{owner}/{repo}",
            owner=owner,
            repo=repo,
            branch=branch,
            sha=sha,
        )

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    locator: str
    sha256: str
    summary: str


@dataclass(frozen=True)
class RepositoryMap:
    repository: RepositoryRef
    default_branch: str
    description: str | None
    language: str | None
    archived: bool
    files: tuple[str, ...]
    directories: tuple[str, ...]
    workflows: tuple[str, ...]
    config_files: tuple[str, ...]
    test_paths: tuple[str, ...]
    stack: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class Finding:
    finding_id: str
    severity: str
    category: str
    description: str
    affected_paths: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    confidence: str


@dataclass(frozen=True)
class AuditReport:
    findings: tuple[Finding, ...]
    blockers: tuple[str, ...]
    next_action: str
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class PlanTask:
    task_id: str
    priority: int
    reason: str
    affected_paths: tuple[str, ...]
    required_change: str
    risk: str
    verification: str
    finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class RepairPlan:
    tasks: tuple[PlanTask, ...]
    plan_hash: str
    summary_pl: str


@dataclass(frozen=True)
class ApprovalRecord:
    action: str
    actor: str
    target_hash: str
    issued_at: str
    expires_at: str
    signature: str


@dataclass
class Run:
    run_id: str
    goal: str
    repo_url: str
    base_branch: str
    state: RunState = RunState.CREATED
    base_sha: str | None = None
    repository: RepositoryRef | None = None
    repository_map: RepositoryMap | None = None
    audit_report: AuditReport | None = None
    repair_plan: RepairPlan | None = None
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    allowed_files: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=lambda: [".git", ".github/workflows/repo-closer*"])
    capabilities: list[str] = field(default_factory=lambda: ["repo.read"])
    allowed_commands: list[list[str]] = field(default_factory=list)
    approvals: list[ApprovalRecord] = field(default_factory=list)
    work_branch: str | None = None
    workspace_id: str | None = None
    diff_text: str | None = None
    diff_hash: str | None = None
    head_sha: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    merge_sha: str | None = None
    build_id: str | None = None
    build_project: str | None = None
    build_region: str | None = None
    image_digest: str | None = None
    built_image: str | None = None
    deployment_target: str | None = None
    deployment_url: str | None = None
    revision: str | None = None
    verification_summary: str | None = None
    iteration: int = 0
    max_iterations: int = 5
    budget_limit: float = 5.0
    spent: float = 0.0
    reserved: float = 0.0
    max_active_seconds: int = 2700
    active_seconds: int = 0
    stop_requested: bool = False
    failure_reason: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    version: int = 0

    @classmethod
    def create(cls, repo_url: str, branch: str, goal: str, **kwargs: Any) -> "Run":
        return cls(run_id=str(uuid.uuid4()), goal=goal, repo_url=repo_url, base_branch=branch, **kwargs)

    def transition(self, new_state: RunState) -> None:
        if new_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"Niedozwolone przejście: {self.state} -> {new_state}")
        self.state = new_state
        self.version += 1
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        def convert(value: Any) -> Any:
            if isinstance(value, StrEnum):
                return str(value)
            if hasattr(value, "__dataclass_fields__"):
                return {k: convert(v) for k, v in asdict(value).items()}
            if isinstance(value, tuple):
                return [convert(v) for v in value]
            if isinstance(value, list):
                return [convert(v) for v in value]
            if isinstance(value, dict):
                return {k: convert(v) for k, v in value.items()}
            return value
        return convert(self)


def _ev(d: dict[str, Any]) -> EvidenceRef:
    return EvidenceRef(**d)


def run_from_dict(data: dict[str, Any]) -> Run:
    d = dict(data)
    d["state"] = RunState(d["state"])
    if d.get("repository"):
        d["repository"] = RepositoryRef(**d["repository"])
    if d.get("repository_map"):
        m = dict(d["repository_map"])
        m["repository"] = RepositoryRef(**m["repository"])
        m["files"] = tuple(m.get("files", []))
        m["directories"] = tuple(m.get("directories", []))
        m["workflows"] = tuple(m.get("workflows", []))
        m["config_files"] = tuple(m.get("config_files", []))
        m["test_paths"] = tuple(m.get("test_paths", []))
        m["stack"] = tuple(m.get("stack", []))
        m["evidence"] = tuple(_ev(x) for x in m.get("evidence", []))
        d["repository_map"] = RepositoryMap(**m)
    if d.get("audit_report"):
        a = dict(d["audit_report"])
        findings = []
        for item in a.get("findings", []):
            x = dict(item)
            x["affected_paths"] = tuple(x.get("affected_paths", []))
            x["evidence"] = tuple(_ev(e) for e in x.get("evidence", []))
            findings.append(Finding(**x))
        a["findings"] = tuple(findings)
        a["blockers"] = tuple(a.get("blockers", []))
        a["evidence"] = tuple(_ev(x) for x in a.get("evidence", []))
        d["audit_report"] = AuditReport(**a)
    if d.get("repair_plan"):
        p = dict(d["repair_plan"])
        tasks = []
        for item in p.get("tasks", []):
            x = dict(item)
            x["affected_paths"] = tuple(x.get("affected_paths", []))
            x["finding_ids"] = tuple(x.get("finding_ids", []))
            tasks.append(PlanTask(**x))
        p["tasks"] = tuple(tasks)
        d["repair_plan"] = RepairPlan(**p)
    d["evidence_refs"] = [_ev(x) for x in d.get("evidence_refs", [])]
    d["approvals"] = [ApprovalRecord(**x) for x in d.get("approvals", [])]
    return Run(**d)
