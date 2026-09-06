from __future__ import annotations

import argparse
import json
from .core import Run
from .github_read import GitHubReadClient
from .persistence import JsonRunStore
from .pipeline import Auditor, Controller, Mapper, Planner


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="OSA Repo Closer — Slice 1 READ-ONLY")
    p.add_argument("repo_url")
    p.add_argument("--branch", default="main")
    p.add_argument("--sha")
    p.add_argument("--goal", default="Przeanalizuj repo i przygotuj evidence-backed plan.")
    p.add_argument("--state-dir", default=".repo-closer/runs")
    a = p.parse_args(argv)
    run = Run.create(a.repo_url, a.branch, a.goal)
    ctl = Controller(
        Mapper(GitHubReadClient()),
        Auditor(),
        Planner(),
        JsonRunStore(a.state_dir),
    )
    out = ctl.execute_slice1(run, a.sha)
    print(json.dumps(out.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
