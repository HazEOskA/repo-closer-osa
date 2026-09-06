from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse
import uuid

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class RunState(StrEnum):
    CREATED = "CREATED"
    MAPPING = "MAPPING"
    AUDITING = "AUDITING"
    PLANNING = "PLANNING"
    AWAITING_FIX_APPROVAL = "AWAITING_FIX_APPROVAL"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


_ALLOWED = {
    RunState.CREATED: {RunState.MAPPING, RunState.STOPPED, RunState.FAILED},
    RunState.MAPPING: {RunState.AUDITING, RunState.STOPPED, RunState.FAILED},
    RunState.AUDITING: {RunState.PLANNING, RunState.STOPPED, RunState.FAILED},
    RunState.PLANNING: {RunState.AWAITING_FIX_APPROVAL, RunState.STOPPED, RunState.FAILED},
    RunState.AWAITING_FIX_APPROVAL: {RunState.STOPPED},
    RunState.STOPPED: set(),
    RunState.FAILED: set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _normalize(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, set):
        return sorted(_normalize(v) for v in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported canonical type: {type(value)!r}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class RepositoryRef:
    url: str
    owner: str
    repo: str
    branch: str
    sha: str

    @classmethod
    def parse(cls, url: str, branch: str, sha: str) -> "RepositoryRef":
        p = urlparse(url.strip())
        if p.scheme != "https" or p.hostname != "github.com":
            raise ValueError("Dozwolone są tylko repozytoria https://github.com/OWNER/REPO.")
        parts = [x for x in p.path.removesuffix(".git").strip("/").split("/") if x]
        if len(parts) != 2:
            raise ValueError("URL musi wskazywać root repozytorium GitHub.")
        owner, repo = parts
        if not _NAME_RE.fullmatch(owner) or not _NAME_RE.fullmatch(repo):
            raise ValueError("Nieprawidłowy owner/repo.")
        if not branch or any(c in branch for c in ("\x00", "\n", "\r")):
            raise ValueError("Nieprawidłowy branch.")
        sha = sha.lower()
        if not _SHA_RE.fullmatch(sha):
            raise ValueError("SHA musi mieć 40 znaków hex.")
        return cls(f"https://github.com/{owner}/{repo}", owner, repo, branch, sha)

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class Evidence:
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
    configs: tuple[str, ...]
    tests: tuple[str, ...]
    stack: tuple[str, ...]
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    category: str
    description: str
    affected_paths: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    confidence: str


@dataclass(frozen=True)
class AuditReport:
    findings: tuple[Finding, ...]
    blockers: tuple[str, ...]
    next_action: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class PlanTask:
    id: str
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


@dataclass
class Run:
    run_id: str
    repo_url: str
    base_branch: str
    goal: str
    state: RunState = RunState.CREATED
    base_sha: str | None = None
    repository: RepositoryRef | None = None
    repository_map: RepositoryMap | None = None
    audit_report: AuditReport | None = None
    repair_plan: RepairPlan | None = None
    failure_reason: str | None = None
    stop_requested: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    version: int = 0

    @classmethod
    def create(cls, repo_url: str, branch: str, goal: str) -> "Run":
        return cls(str(uuid.uuid4()), repo_url, branch, goal)

    def transition(self, target: RunState) -> None:
        if target not in _ALLOWED[self.state]:
            raise ValueError(f"Niedozwolone przejście {self.state} -> {target}")
        self.state = target
        self.version += 1
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return _normalize(self)
