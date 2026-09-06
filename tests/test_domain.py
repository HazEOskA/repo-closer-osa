import pytest
from repo_closer.domain import RepositoryRef, Run, RunState


SHA = "a" * 40


def test_repository_ref_canonicalizes_and_requires_full_sha():
    ref = RepositoryRef.parse("https://github.com/HazEOskA/example.git", "main", SHA)
    assert ref.url == "https://github.com/HazEOskA/example"
    assert ref.slug == "HazEOskA/example"
    with pytest.raises(ValueError):
        RepositoryRef.parse("https://gitlab.com/x/y", "main", SHA)
    with pytest.raises(ValueError):
        RepositoryRef.parse("https://github.com/x/y/tree/main", "main", SHA)
    with pytest.raises(ValueError):
        RepositoryRef.parse("https://github.com/x/y", "main", "abc")


def test_state_machine_rejects_skipping_approval_boundary():
    run = Run.create("https://github.com/x/y", "main", "goal")
    with pytest.raises(ValueError):
        run.transition(RunState.PLANNING)
