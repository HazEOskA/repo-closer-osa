from __future__ import annotations
from .canonical import sha256_hex
from .domain import AuditReport, PlanTask, RepairPlan

_SEVERITY_PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class Planner:
    def plan(self, audit: AuditReport) -> RepairPlan:
        ordered = sorted(audit.findings, key=lambda f: (_SEVERITY_PRIORITY.get(f.severity, 9), f.finding_id))
        tasks: list[PlanTask] = []
        for idx, finding in enumerate(ordered, start=1):
            tasks.append(PlanTask(
                task_id=f"T{idx:03d}",
                priority=idx,
                reason=finding.description,
                affected_paths=finding.affected_paths,
                required_change="Przygotuj minimalną zmianę rozwiązującą finding bez rozszerzania scope.",
                risk=finding.severity,
                verification="W kolejnym slice wymagany będzie test/review przypięty do konkretnego diffu i SHA.",
                finding_ids=(finding.finding_id,),
            ))

        hash_payload = [{
            "task_id": t.task_id,
            "priority": t.priority,
            "reason": t.reason,
            "affected_paths": list(t.affected_paths),
            "required_change": t.required_change,
            "risk": t.risk,
            "verification": t.verification,
            "finding_ids": list(t.finding_ids),
        } for t in tasks]
        plan_hash = sha256_hex(hash_payload)
        summary = (
            f"Plan zawiera {len(tasks)} zadań. Nie wykonano żadnej zmiany w analizowanym repo. "
            "Run czeka na osobną zgodę na etap naprawczy."
        )
        return RepairPlan(tasks=tuple(tasks), plan_hash=plan_hash, summary_pl=summary)
