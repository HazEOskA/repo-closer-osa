import inspect
from repo_closer.github_read import GitHubReadClient


def test_github_adapter_exposes_no_write_verbs():
    names = {name.lower() for name, _ in inspect.getmembers(GitHubReadClient, inspect.isfunction)}
    forbidden = {"post", "put", "patch", "delete", "push", "merge", "deploy", "create_pr", "create_branch"}
    assert not (names & forbidden)
