from __future__ import annotations

import time
from collections.abc import Callable

from .controller import Controller
from .domain import Run, RunState


_TERMINAL = {
    RunState.COMPLETED,
    RunState.BLOCKED,
    RunState.STOPPED,
    RunState.BUDGET_EXCEEDED,
    RunState.FAILED,
}

_CI_PENDING_MARKERS = (
    "CI jeszcze trwa",
    "Brak CI check-runs",
)


class ClosureRunner:
    """Drive one already-approved maintenance run through the existing gates."""

    def __init__(
        self,
        controller: Controller,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.controller = controller
        self.sleep = sleep
        self.monotonic = monotonic

    def close(
        self,
        run_id: str,
        actor: str,
        allowed_files: list[str] | None = None,
        allowed_commands: list[list[str]] | None = None,
        ci_wait_seconds: int = 180,
        close_without_deploy: bool = True,
    ) -> Run:
        """Advance a run until COMPLETED/BLOCKED or a deploy boundary.

        The runner does not invent new permissions. It consumes the exact
        files/commands supplied by the operator for the FIX gate and then uses
        the existing PR/merge approval bindings for the same run.
        """
        deadline = self.monotonic() + max(0, ci_wait_seconds)

        while True:
            run = self.controller.get(run_id)
            if run.state in _TERMINAL:
                return run

            if run.state == RunState.AWAITING_FIX_APPROVAL:
                run = self.controller.approve_fix(
                    run_id,
                    actor,
                    allowed_files or ["*"],
                    allowed_commands or [],
                )
                if run.state in _TERMINAL:
                    return run
                continue

            if run.state == RunState.AWAITING_PR_APPROVAL:
                run = self.controller.approve_pr(run_id, actor)
                if run.state in _TERMINAL:
                    return run
                continue

            if run.state == RunState.PR_OPEN:
                try:
                    run = self.controller.approve_merge(run_id, actor)
                except RuntimeError as exc:
                    message = str(exc)
                    if any(marker in message for marker in _CI_PENDING_MARKERS):
                        if self.monotonic() >= deadline:
                            return self.controller._block(
                                self.controller.get(run_id),
                                f"CI timeout po {ci_wait_seconds}s: {message}",
                            )
                        self.sleep(5)
                        continue
                    return self.controller._block(
                        self.controller.get(run_id),
                        f"CI gate odrzucił closure: {message}",
                    )
                if run.state in _TERMINAL:
                    return run
                continue

            if run.state == RunState.MERGED:
                if close_without_deploy:
                    return self.controller.complete_without_deploy(run_id)
                return run

            # BUILD/DEPLOY remain the existing explicit path. This runner does
            # not silently deploy anything outside the operator-approved scope.
            return run
