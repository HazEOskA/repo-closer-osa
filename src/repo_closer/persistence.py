from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from .domain import Run, run_from_dict


class RunRepository(Protocol):
    def save(self, run: Run) -> None: ...
    def get(self, run_id: str) -> Run | None: ...


class InMemoryRunRepository:
    def __init__(self):
        self._runs: dict[str, dict] = {}
        self.runs = self._runs
    def save(self, run: Run) -> None: self._runs[run.run_id] = run.to_dict()
    def get(self, run_id: str) -> Run | None:
        data = self._runs.get(run_id)
        return run_from_dict(data) if data else None


class JsonRunRepository:
    def __init__(self, root: str = ".repo-closer/runs"):
        self.root = Path(root)
    def save(self, run: Run) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{run.run_id}.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        temp.replace(target)
    def get(self, run_id: str) -> Run | None:
        target = self.root / f"{run_id}.json"
        return run_from_dict(json.loads(target.read_text())) if target.exists() else None


class FirestoreRunRepository:
    def __init__(self, project: str | None = None, collection: str = "maintenance_runs"):
        from google.cloud import firestore
        self.client = firestore.Client(project=project)
        self.collection = self.client.collection(collection)
    def save(self, run: Run) -> None:
        self.collection.document(run.run_id).set(run.to_dict())
    def get(self, run_id: str) -> Run | None:
        snap = self.collection.document(run_id).get()
        return run_from_dict(snap.to_dict()) if snap.exists else None


def default_repository() -> RunRepository:
    if os.getenv("MAINTENANCE_STORE", "firestore") == "json":
        return JsonRunRepository(os.getenv("MAINTENANCE_STATE_DIR", ".repo-closer/runs"))
    return FirestoreRunRepository(project=os.getenv("GOOGLE_CLOUD_PROJECT"))

MemoryRunRepository = InMemoryRunRepository
