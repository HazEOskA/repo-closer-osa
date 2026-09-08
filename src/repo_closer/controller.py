from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import os
import subprocess

from .approval import ApprovalAuthority
from .auditor import Auditor
from .canonical import sha256_hex
from .domain import Run, RunState, RepositoryRef
from .gcp import GCPAdapter
from .github_write import GitHubWriteClient
from .llm import VertexFixerModel
from .mapper import Mapper
from .patching import apply_patch, strip_code_fence, validate_patch
from .persistence import RunRepository
from .planner import Planner
from .policy import PolicyEngine
from .reviewer import Reviewer
from .workspace import WorkspaceManager


class Controller:
    def __init__(
        self,
        mapper: Mapper,
        auditor: Auditor,
        planner: Planner,
        runs: RunRepository,
        approvals: ApprovalAuthority | None = None,
        policy: PolicyEngine | None = None,
        workspaces: WorkspaceManager | None = None,
        model: VertexFixerModel | None = None,
        reviewer: Reviewer | None = None,
        github_write: GitHubWriteClient | None = None,
        gcp: GCPAdapter | None = None,
    ):
        self.mapper = mapper
        self.auditor = auditor
        self.planner = planner
        self.runs = runs
        self.approvals = approvals
        self.policy = policy or PolicyEngine()
        self.workspaces = workspaces or WorkspaceManager()
        self.model = model
        self.reviewer = reviewer or Reviewer(self.policy)
        self.github_write = github_write
        self.gcp = gcp or GCPAdapter()

    def _save(self, run: Run) -> Run:
        self.runs.save(run)
        return run

    def get(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if not run:
            raise KeyError(run_id)
        return run

    def start(self, run: Run, requested_sha: str | None = None) -> Run:
        if run.state != RunState.CREATED:
            raise ValueError("Run można rozpocząć wyłącznie z CREATED.")
        try:
            run.transition(RunState.MAPPING); self._save(run)
            repository = self.mapper.resolve_repository(run.repo_url, run.base_branch, requested_sha=requested_sha)
            repo_map = self.mapper.map(repository)
            run.repository = repository
            run.base_sha = repository.sha
            run.repository_map = repo_map
            run.evidence_refs.extend(repo_map.evidence)
            if run.stop_requested: run.transition(RunState.STOPPED); return self._save(run)

            run.transition(RunState.AUDITING); self._save(run)
            audit = self.auditor.audit(repo_map)
            run.audit_report = audit
            run.evidence_refs = list(audit.evidence)
            if run.stop_requested: run.transition(RunState.STOPPED); return self._save(run)

            run.transition(RunState.PLANNING); self._save(run)
            run.repair_plan = self.planner.plan(audit)
            run.transition(RunState.AWAITING_FIX_APPROVAL)
            return self._save(run)
        except Exception as exc:
            return self._fail(run, exc)

    def execute_slice1(self, run: Run, requested_sha: str | None = None) -> Run:
        return self.start(run, requested_sha)

    def _authority(self) -> ApprovalAuthority:
        if not self.approvals:
            raise RuntimeError("ApprovalAuthority nie jest skonfigurowany.")
        return self.approvals

    def approve_fix(
        self,
        run_id: str,
        actor: str,
        allowed_files: list[str] | None,
        allowed_commands: list[list[str]] | None,
        ttl_minutes: int = 60,
    ) -> Run:
        run = self.get(run_id)
        if run.state != RunState.AWAITING_FIX_APPROVAL:
            raise ValueError("Run nie czeka na zgodę naprawczą.")
        target = {
            "allowed_files": allowed_files or ["*"],
            "allowed_commands": allowed_commands or [],
            "capabilities": ["repo.read", "repo.patch", "tests.run"],
        }
        record = self._authority().issue(run, "fix", actor, target, ttl_minutes)
        if not self._authority().verify(run, record, "fix", target):
            raise RuntimeError("Approval binding verification failed.")
        run.approvals.append(record)
        run.allowed_files = list(target["allowed_files"])
        run.allowed_commands = [list(x) for x in target["allowed_commands"]]
        run.capabilities = list(target["capabilities"])
        run.transition(RunState.FIXING)
        self._save(run)
        return self._fix_review_loop(run)

    def _fix_review_loop(self, run: Run, feedback: str | None = None) -> Run:
        if not run.repository:
            raise RuntimeError("Brak RepositoryRef.")
        if not self.model:
            return self._block(run, "Brak skonfigurowanego modelu Vertex AI.")
        self.policy.require_capability(run, "repo.patch")
        token = os.getenv("GITHUB_TOKEN")
        while run.iteration < run.max_iterations:
            run.iteration += 1
            workspace = None
            try:
                workspace = self.workspaces.create(run.repository, run.run_id, token)
                patch = strip_code_fence(self.model.generate_patch(run, workspace, feedback))
                _, patch_hash = validate_patch(run, patch, self.policy)
                apply_patch(workspace, patch)
                run.transition(RunState.REVIEWING); self._save(run)
                review = self.reviewer.review(run, workspace, patch)
                if review.passed:
                    diff = subprocess.check_output(["git", "diff", "--no-ext-diff", "--binary"], cwd=workspace, text=True)
                    validate_patch(run, diff, self.policy)
                    run.diff_text = diff
                    run.diff_hash = sha256_hex(diff)
                    run.verification_summary = review.summary
                    run.transition(RunState.AWAITING_PR_APPROVAL)
                    return self._save(run)
                feedback = review.summary + "\n" + "\n".join(x.get("output", "")[-3000:] for x in review.command_results if x.get("returncode"))
                run.transition(RunState.FIXING); self._save(run)
            except Exception as exc:
                feedback = f"{type(exc).__name__}: {exc}"
                if run.state == RunState.REVIEWING:
                    run.transition(RunState.FIXING); self._save(run)
            finally:
                if workspace:
                    self.workspaces.cleanup(workspace)
        run.failure_reason = f"Wyczerpano max_iterations={run.max_iterations}. Ostatni feedback: {feedback}"
        run.transition(RunState.FAILED)
        return self._save(run)

    def approve_pr(self, run_id: str, actor: str, ttl_minutes: int = 60) -> Run:
        run = self.get(run_id)
        if run.state != RunState.AWAITING_PR_APPROVAL or not run.diff_text or not run.diff_hash or not run.repository:
            raise ValueError("Run nie ma zatwierdzalnego diffu.")
        if not self.github_write:
            return self._block(run, "Brak GITHUB_TOKEN / GitHub write adapter.")
        work_branch = run.work_branch or f"repo-closer/{run.run_id[:8]}"
        target = {"diff_hash": run.diff_hash, "work_branch": work_branch}
        record = self._authority().issue(run, "pr", actor, target, ttl_minutes)
        if not self._authority().verify(run, record, "pr", target):
            raise RuntimeError("PR approval binding verification failed.")
        run.approvals.append(record)
        run.capabilities = sorted(set(run.capabilities) | {"repo.push", "pr.create"})
        run.work_branch = work_branch
        run.transition(RunState.PUBLISHING_PR); self._save(run)
        workspace = None
        try:
            workspace = self.workspaces.create(run.repository, run.run_id, os.getenv("GITHUB_TOKEN"))
            apply_patch(workspace, run.diff_text)
            head_sha = self.github_write.publish_branch(
                run.repository, workspace, work_branch,
                f"repo-closer: maintenance run {run.run_id[:8]}"
            )
            run.head_sha = head_sha
            if not run.pr_url:
                run.pr_url, run.pr_number = self.github_write.create_pr(
                    run.repository, work_branch,
                    f"Repo Closer: {run.goal[:72]}",
                    f"Automatyczny maintenance run `{run.run_id}`.\n\nPlan: `{run.repair_plan.plan_hash if run.repair_plan else 'n/a'}`\nDiff: `{run.diff_hash}`\nReview: {run.verification_summary}"
                )
            run.transition(RunState.PR_OPEN)
            return self._save(run)
        except Exception as exc:
            return self._fail(run, exc)
        finally:
            if workspace: self.workspaces.cleanup(workspace)

    def approve_merge(self, run_id: str, actor: str, ttl_minutes: int = 30) -> Run:
        run = self.get(run_id)
        if (
            run.state != RunState.PR_OPEN
            or not run.repository
            or not run.pr_url
            or not run.pr_number
            or not run.head_sha
        ):
            raise ValueError("Merge wymaga PR_OPEN, pr_number i przypiętego head_sha.")
        if not self.github_write:
            return self._block(run, "Brak GITHUB_TOKEN / GitHub write adapter.")

        # Check CI before issuing a mutation approval. merge_pr repeats the check
        # immediately before the write to protect against race/drift.
        self.github_write.require_successful_checks(run.repository, run.head_sha)
        target = {
            "pr_number": run.pr_number,
            "pr_url": run.pr_url,
            "head_sha": run.head_sha,
            "base_sha": run.base_sha,
            "base_branch": run.repository.branch,
        }
        record = self._authority().issue(run, "merge", actor, target, ttl_minutes)
        if not self._authority().verify(run, record, "merge", target):
            raise RuntimeError("Merge approval binding verification failed.")
        run.approvals.append(record)
        run.capabilities = sorted(set(run.capabilities) | {"repo.merge"})
        run.transition(RunState.MERGING); self._save(run)
        try:
            run.merge_sha = self.github_write.merge_pr(run.repository, run.pr_number, run.head_sha)
            run.transition(RunState.MERGED)
            return self._save(run)
        except Exception as exc:
            return self._fail(run, exc)

    def build(self, run_id: str, project: str, region: str, artifact_repo: str, image_name: str, deployment_target: str) -> Run:
        run = self.get(run_id)
        if run.state != RunState.MERGED or not run.repository or not run.merge_sha:
            raise ValueError("Build wymaga MERGED i canonical merge_sha.")
        run.capabilities = sorted(set(run.capabilities) | {"gcp.build"})
        run.transition(RunState.BUILDING); self._save(run)
        workspace = None
        try:
            build_repo = RepositoryRef(
                run.repository.url,
                run.repository.owner,
                run.repository.repo,
                run.repository.branch,
                run.merge_sha,
            )
            workspace = self.workspaces.create(build_repo, run.run_id, os.getenv("GITHUB_TOKEN"))
            result = self.gcp.build(workspace, project, region, artifact_repo, image_name, run.merge_sha)
            run.build_id = result.build_id
            run.build_project = project
            run.build_region = region
            run.image_digest = result.digest
            run.built_image = result.immutable_image
            run.deployment_target = deployment_target
            run.deployment_url = None
            run.transition(RunState.AWAITING_DEPLOY_APPROVAL)
            return self._save(run)
        except Exception as exc:
            return self._fail(run, exc)
        finally:
            if workspace: self.workspaces.cleanup(workspace)

    def approve_deploy(
        self,
        run_id: str,
        actor: str,
        service_account: str | None = None,
        health_path: str = "/health",
        ttl_minutes: int = 30,
    ) -> Run:
        run = self.get(run_id)
        if run.state != RunState.AWAITING_DEPLOY_APPROVAL:
            raise ValueError("Run nie czeka na deploy approval.")
        if not all((
            run.build_id,
            run.build_project,
            run.build_region,
            run.image_digest,
            run.built_image,
            run.deployment_target,
            run.merge_sha,
        )):
            raise ValueError("Brak kompletnego immutable build evidence do deployu.")
        if "@sha256:" not in run.built_image:
            raise ValueError("built_image nie jest immutable image@sha256:digest.")

        target = {
            "project": run.build_project,
            "region": run.build_region,
            "service": run.deployment_target,
            "image": run.built_image,
            "image_digest": run.image_digest,
            "merge_sha": run.merge_sha,
            "build_id": run.build_id,
        }
        record = self._authority().issue(run, "deploy", actor, target, ttl_minutes)
        if not self._authority().verify(run, record, "deploy", target):
            raise RuntimeError("Deploy approval binding verification failed.")
        run.approvals.append(record)
        run.capabilities = sorted(set(run.capabilities) | {"gcp.deploy", "verify.http"})
        run.transition(RunState.DEPLOYING); self._save(run)
        try:
            from .gcp import BuildResult
            build = BuildResult(
                run.build_id,
                run.built_image,
                run.image_digest,
                run.built_image,
            )
            deployed = self.gcp.deploy(
                build,
                run.build_project,
                run.build_region,
                run.deployment_target,
                service_account,
            )
            run.revision = deployed.revision
            run.deployment_url = deployed.url
            run.transition(RunState.VERIFYING); self._save(run)
            ok, detail = self.gcp.verify(deployed.url, health_path)
            run.verification_summary = detail
            if ok:
                run.transition(RunState.COMPLETED)
                return self._save(run)

            if run.iteration < run.max_iterations and run.merge_sha and run.repository:
                run.repository = RepositoryRef(
                    run.repository.url,
                    run.repository.owner,
                    run.repository.repo,
                    run.repository.branch,
                    run.merge_sha,
                )
                run.base_sha = run.merge_sha
                run.diff_text = None
                run.diff_hash = None
                run.work_branch = None
                run.head_sha = None
                run.pr_url = None
                run.pr_number = None
                run.merge_sha = None
                run.build_id = None
                run.build_project = None
                run.build_region = None
                run.image_digest = None
                run.built_image = None
                run.revision = None
                run.deployment_url = None
                run.goal = run.goal + f"\nBłąd po deploy: {detail[-2000:]}"
                run.transition(RunState.FIXING); self._save(run)
                return self._fix_review_loop(run, feedback=detail)

            run.failure_reason = f"Verify FAIL: {detail[-3000:]}"
            run.transition(RunState.FAILED)
            return self._save(run)
        except Exception as exc:
            return self._fail(run, exc)

    def complete_without_deploy(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run.state != RunState.MERGED:
            raise ValueError("Tylko MERGED może zakończyć się bez deployu.")
        run.transition(RunState.COMPLETED)
        return self._save(run)

    def stop(self, run_id: str) -> Run:
        run = self.get(run_id)
        run.stop_requested = True
        if run.state not in {RunState.COMPLETED, RunState.STOPPED, RunState.FAILED, RunState.BLOCKED, RunState.BUDGET_EXCEEDED}:
            run.transition(RunState.STOPPED)
        return self._save(run)

    def _block(self, run: Run, reason: str) -> Run:
        run.failure_reason = reason
        if run.state != RunState.BLOCKED:
            run.transition(RunState.BLOCKED)
        return self._save(run)

    def _fail(self, run: Run, exc: Exception) -> Run:
        run.failure_reason = f"{type(exc).__name__}: {exc}"
        if run.state not in {RunState.COMPLETED, RunState.STOPPED, RunState.FAILED, RunState.BLOCKED, RunState.BUDGET_EXCEEDED}:
            run.transition(RunState.FAILED)
        self._save(run)
        raise exc
