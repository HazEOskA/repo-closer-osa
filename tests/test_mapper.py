from repo_closer.mapper import Mapper


SHA = "1" * 40
TREE = "2" * 40


class FakeGitHub:
    def repo_meta(self, owner, repo):
        return {"default_branch": "main", "description": "demo", "language": "Python", "archived": False}
    def commit(self, owner, repo, ref):
        return {"sha": SHA, "commit": {"tree": {"sha": TREE}}}
    def tree(self, owner, repo, tree_sha):
        return {"truncated": False, "tree": [
            {"type": "blob", "path": "README.md"},
            {"type": "blob", "path": "pyproject.toml"},
            {"type": "blob", "path": "tests/test_app.py"},
            {"type": "blob", "path": ".github/workflows/ci.yml"},
            {"type": "tree", "path": "tests"},
        ]}
    def file_text(self, owner, repo, path, ref):
        return {"README.md": "# hi", "pyproject.toml": "[project]\nname='x'"}.get(path)


def test_mapper_pins_sha_and_discovers_repo_structure():
    mapper = Mapper(FakeGitHub())
    ref = mapper.resolve_repository("https://github.com/acme/demo", "main")
    assert ref.sha == SHA
    mapped = mapper.map(ref)
    assert mapped.stack == ("python",)
    assert mapped.test_paths == ("tests/test_app.py",)
    assert mapped.workflows == (".github/workflows/ci.yml",)
    assert "pyproject.toml" in mapped.config_files


def test_requested_sha_must_match():
    mapper = Mapper(FakeGitHub())
    try:
        mapper.resolve_repository("https://github.com/acme/demo", "main", requested_sha="f"*40)
    except ValueError as exc:
        assert "inny" in str(exc)
    else:
        raise AssertionError("Expected mismatch rejection")
