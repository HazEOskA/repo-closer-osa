from __future__ import annotations

import os
import secrets
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .approval import ApprovalAuthority
from .auditor import Auditor
from .controller import Controller
from .domain import Run
from .github_read import GitHubReadClient
from .github_write import GitHubWriteClient
from .llm import VertexFixerModel
from .mapper import Mapper
from .persistence import default_repository
from .planner import Planner
from .runner import ClosureRunner
from .ui import DASHBOARD_HTML

app = FastAPI(title="OSA Repo Closer", version="0.3.0")


def _token_guard(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("MAINTENANCE_API_TOKEN")
    if not expected:
        raise HTTPException(503, "MAINTENANCE_API_TOKEN nie jest skonfigurowany.")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, "Unauthorized")


def make_controller() -> Controller:
    secret = os.getenv("MAINTENANCE_APPROVAL_SECRET")
    if not secret:
        raise RuntimeError("Brak MAINTENANCE_APPROVAL_SECRET.")
    token = os.getenv("GITHUB_TOKEN")
    writer = GitHubWriteClient(token) if token else None
    model = VertexFixerModel() if os.getenv("GOOGLE_CLOUD_PROJECT") else None
    return Controller(
        Mapper(GitHubReadClient(token)), Auditor(), Planner(), default_repository(),
        approvals=ApprovalAuthority(secret), model=model, github_write=writer,
    )


class StartRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    sha: str | None = None
    goal: str
    max_iterations: int = Field(default=5, ge=1, le=10)
    budget_limit: float = Field(default=5.0, ge=0.1, le=100.0)


class ClosureRequest(StartRequest):
    actor: str = "operator"
    allowed_files: list[str] = Field(default_factory=lambda: ["*"])
    allowed_commands: list[list[str]]
    ci_wait_seconds: int = Field(default=180, ge=0, le=900)
    close_without_deploy: bool = True


class FixApproval(BaseModel):
    actor: str = "operator"
    allowed_files: list[str] = Field(default_factory=lambda: ["*"])
    allowed_commands: list[list[str]] = Field(default_factory=list)


class ActorRequest(BaseModel):
    actor: str = "operator"


class BuildRequest(BaseModel):
    project: str
    region: str
    artifact_repo: str
    image_name: str
    deployment_target: str


class DeployApproval(BaseModel):
    actor: str = "operator"
    service_account: str | None = None
    health_path: str = "/health"


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/health")
def health():
    return {"ok": True, "service": "osa-repo-closer", "version": "0.3.0"}


@app.post("/closures", dependencies=[Depends(_token_guard)])
def close_repo(req: ClosureRequest):
    try:
        controller = make_controller()
        run = Run.create(
            req.repo_url,
            req.branch,
            req.goal,
            max_iterations=req.max_iterations,
            budget_limit=req.budget_limit,
        )
        run = controller.start(run, req.sha)
        if run.state.value != "AWAITING_FIX_APPROVAL":
            return run.to_dict()
        return ClosureRunner(controller).close(
            run.run_id,
            req.actor,
            req.allowed_files,
            req.allowed_commands,
            ci_wait_seconds=req.ci_wait_seconds,
            close_without_deploy=req.close_without_deploy,
        ).to_dict()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/runs", dependencies=[Depends(_token_guard)])
def start(req: StartRequest):
    try:
        run = Run.create(req.repo_url, req.branch, req.goal, max_iterations=req.max_iterations, budget_limit=req.budget_limit)
        return make_controller().start(run, req.sha).to_dict()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/runs/{run_id}", dependencies=[Depends(_token_guard)])
def get_run(run_id: str):
    try: return make_controller().get(run_id).to_dict()
    except KeyError as exc: raise HTTPException(404, "Run not found") from exc


@app.post("/runs/{run_id}/approve-fix", dependencies=[Depends(_token_guard)])
def approve_fix(run_id: str, req: FixApproval):
    try: return make_controller().approve_fix(run_id, req.actor, req.allowed_files, req.allowed_commands).to_dict()
    except Exception as exc: raise HTTPException(400, str(exc)) from exc


@app.post("/runs/{run_id}/approve-pr", dependencies=[Depends(_token_guard)])
def approve_pr(run_id: str, req: ActorRequest):
    try: return make_controller().approve_pr(run_id, req.actor).to_dict()
    except Exception as exc: raise HTTPException(400, str(exc)) from exc


@app.post("/runs/{run_id}/approve-merge", dependencies=[Depends(_token_guard)])
def approve_merge(run_id: str, req: ActorRequest):
    try: return make_controller().approve_merge(run_id, req.actor).to_dict()
    except Exception as exc: raise HTTPException(400, str(exc)) from exc


@app.post("/runs/{run_id}/build", dependencies=[Depends(_token_guard)])
def build(run_id: str, req: BuildRequest):
    try: return make_controller().build(run_id, req.project, req.region, req.artifact_repo, req.image_name, req.deployment_target).to_dict()
    except Exception as exc: raise HTTPException(400, str(exc)) from exc


@app.post("/runs/{run_id}/approve-deploy", dependencies=[Depends(_token_guard)])
def approve_deploy(run_id: str, req: DeployApproval):
    try: return make_controller().approve_deploy(run_id, req.actor, req.service_account, req.health_path).to_dict()
    except Exception as exc: raise HTTPException(400, str(exc)) from exc


@app.post("/runs/{run_id}/stop", dependencies=[Depends(_token_guard)])
def stop(run_id: str):
    try: return make_controller().stop(run_id).to_dict()
    except Exception as exc: raise HTTPException(400, str(exc)) from exc


def main() -> None:
    import uvicorn
    uvicorn.run("repo_closer.api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
