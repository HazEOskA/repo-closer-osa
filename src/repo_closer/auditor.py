from __future__ import annotations
from .canonical import sha256_hex
from .domain import AuditReport, EvidenceRef, Finding, RepositoryMap


def _ev(repo_map: RepositoryMap, kind: str, summary: str, payload: object) -> EvidenceRef:
    return EvidenceRef(
        kind=kind,
        locator=f"github:{repo_map.repository.slug}@{repo_map.repository.sha}:derived/{kind}",
        sha256=sha256_hex(payload),
        summary=summary,
    )


class Auditor:
    """Deterministic Slice-1 auditor. No repository code execution and no LLM side effects."""

    def audit(self, repo_map: RepositoryMap) -> AuditReport:
        findings: list[Finding] = []
        derived: list[EvidenceRef] = []

        def add(fid: str, severity: str, category: str, description: str,
                paths: tuple[str, ...], confidence: str, evidence_payload: object):
            evidence = _ev(repo_map, fid, description, evidence_payload)
            derived.append(evidence)
            findings.append(Finding(
                finding_id=fid,
                severity=severity,
                category=category,
                description=description,
                affected_paths=paths,
                evidence=(evidence,),
                confidence=confidence,
            ))

        if repo_map.archived:
            add("repo-archived", "high", "lifecycle",
                "Repozytorium jest oznaczone jako archived.",
                (), "high", {"archived": True})

        if not repo_map.test_paths:
            add("tests-missing", "medium", "testing",
                "Nie wykryto ścieżek testowych w drzewie repozytorium.",
                (), "medium", {"test_paths": []})

        if not repo_map.workflows:
            add("ci-missing", "medium", "ci",
                "Nie wykryto workflow GitHub Actions.",
                (".github/workflows",), "high", {"workflows": []})

        if not any(p.rsplit("/", 1)[-1].startswith("README") for p in repo_map.files):
            add("readme-missing", "low", "documentation",
                "Nie wykryto README.",
                (), "high", {"readme": False})

        if repo_map.stack == ("unknown",):
            add("stack-unknown", "medium", "architecture",
                "Nie udało się określić podstawowego stacku z bezpiecznej listy konfiguracji.",
                repo_map.config_files, "medium", {"configs": repo_map.config_files})

        env_files = tuple(p for p in repo_map.files if p.rsplit("/", 1)[-1] in {".env", ".env.local", ".env.production"})
        if env_files:
            add("env-file-tracked", "high", "security",
                "W drzewie repo wykryto plik środowiskowy, który może zawierać sekrety.",
                env_files, "medium", {"env_files": env_files})

        blockers = tuple(f.description for f in findings if f.severity == "high")
        next_action = (
            "Najpierw rozwiąż finding o najwyższym priorytecie i zweryfikuj go evidence."
            if findings else
            "Brak statycznych findingów Slice 1; przed zmianami wymagany jest osobny zatwierdzony scope."
        )
        return AuditReport(
            findings=tuple(findings),
            blockers=blockers,
            next_action=next_action,
            evidence=tuple((*repo_map.evidence, *derived)),
        )
