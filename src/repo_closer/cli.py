from __future__ import annotations

import argparse
import json
from .auditor import Auditor
from .controller import Controller
from .domain import Run
from .github_read import GitHubReadClient
from .mapper import Mapper
from .persistence import JsonRunRepository
from .planner import Planner


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="OSA Repo Closer")
    p.add_argument("repo_url")
    p.add_argument("--branch", default="main")
    p.add_argument("--sha")
    p.add_argument("--goal", default="Przeanalizuj repo i przygotuj evidence-backed plan.")
    p.add_argument("--state-dir", default=".repo-closer/runs")
    args = p.parse_args(argv)
    controller = Controller(Mapper(GitHubReadClient()), Auditor(), Planner(), JsonRunRepository(args.state_dir))
    run = controller.start(Run.create(args.repo_url, args.branch, args.goal), args.sha)
    print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0
