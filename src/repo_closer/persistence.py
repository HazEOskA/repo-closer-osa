from __future__ import annotations

import json
from pathlib import Path


class MemoryRunStore:
    def __init__(self):
        self.runs = {}

    def save(self, run):
        self.runs[run.run_id] = run.to_dict()


class JsonRunStore:
    def __init__(self, root=".repo-closer/runs"):
        self.root = Path(root)

    def save(self, run):
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{run.run_id}.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        temp.replace(target)
