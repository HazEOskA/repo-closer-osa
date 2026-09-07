"""Structural guards for the Cloud Build pipeline.

These cover the failure classes that already broke real builds: an undeclared
substitution, a critical command silenced with `|| true`, and IAM creep on the
runtime service account.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

CONFIG = Path(__file__).resolve().parents[1] / "cloudbuild.yaml"

# Substitutions Cloud Build provides itself; everything else must be declared.
BUILTIN_SUBSTITUTIONS = {
    "PROJECT_ID", "PROJECT_NUMBER", "BUILD_ID", "LOCATION", "COMMIT_SHA",
    "SHORT_SHA", "REVISION_ID", "REPO_NAME", "REPO_FULL_NAME", "BRANCH_NAME",
    "TAG_NAME", "TRIGGER_NAME", "SERVICE_ACCOUNT", "SERVICE_ACCOUNT_EMAIL",
    "TRIGGER_BUILD_CONFIG_PATH",
}

# Roles the running service needs just to serve requests.
CORE_RUNTIME_ROLES = {
    "roles/datastore.user",
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/secretmanager.secretAccessor",
}

# Roles needed only by the service's own BUILDING/DEPLOYING stages. They are
# broad, so they must stay behind the _GRANT_RUNTIME_DEPLOY_ROLES switch.
DEPLOY_STAGE_ROLES = {
    "roles/cloudbuild.builds.editor",
    "roles/run.admin",
    "roles/artifactregistry.writer",
    "roles/iam.serviceAccountUser",
    "roles/storage.admin",
}

ALLOWED_RUNTIME_ROLES = CORE_RUNTIME_ROLES | DEPLOY_STAGE_ROLES


@pytest.fixture(scope="module")
def raw() -> str:
    return CONFIG.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config(raw: str) -> dict:
    return yaml.safe_load(raw)


def _step(config: dict, step_id: str) -> dict:
    for step in config["steps"]:
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"step {step_id!r} missing")


def _script(step: dict) -> str:
    return "\n".join(str(a) for a in step.get("args", []))


def test_yaml_parses_and_declares_the_expected_steps(config):
    assert [s["id"] for s in config["steps"]] == [
        "ensure-infra", "build", "push", "deploy", "smoke"
    ]


def test_every_substitution_is_declared_or_builtin(raw):
    declared = set(yaml.safe_load(raw).get("substitutions", {}))
    # `$$` is an escaped literal dollar (shell variables), not a substitution.
    without_escapes = raw.replace("$$", "")
    used = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", without_escapes))
    unknown = used - declared - BUILTIN_SUBSTITUTIONS
    assert not unknown, f"undeclared Cloud Build substitutions: {sorted(unknown)}"


def test_ensure_infra_does_not_silence_failures(config):
    script = _script(_step(config, "ensure-infra"))
    assert "|| true" not in script
    assert "set +e" not in script


def test_ensure_infra_is_idempotent_for_created_resources(config):
    script = _script(_step(config, "ensure-infra"))
    for probe in (
        "gcloud artifacts repositories describe",
        "gcloud iam service-accounts describe",
        "gcloud secrets describe",
        "gcloud firestore databases describe",
    ):
        assert probe in script, f"missing existence probe: {probe}"


def _iam_bindings(script: str) -> list[str]:
    """Return each add-iam-policy-binding invocation as one joined command."""
    joined = re.sub(r"\\\n\s*", " ", script)
    commands = [line for line in joined.splitlines() if "add-iam-policy-binding" in line]
    # Drop the `|| fail "...needs roles/x"` diagnostic tail: it names deployer
    # prerequisites, not roles the binding actually grants.
    return [re.split(r"\|\| fail", c)[0] for c in commands]


def test_runtime_service_account_gets_no_admin_roles(config):
    script = _script(_step(config, "ensure-infra"))
    granted: set[str] = set()

    # Roles bound through the `for role in ...` loop over the project policy.
    for loop in re.findall(r"for role in ([^;\n]+?); do", script):
        granted.update(re.findall(r"roles/[a-zA-Z0-9._]+", loop))
    assert granted, "no project-level runtime roles found"

    # Roles bound literally in a command whose member is the runtime SA.
    for command in _iam_bindings(script):
        if '--member="serviceAccount:$$RUNTIME_SA"' not in command:
            continue  # binding targets the deployer, not the running service
        granted.update(re.findall(r"--role=\"?(roles/[a-zA-Z0-9._]+)", command))

    escalated = granted - ALLOWED_RUNTIME_ROLES
    assert not escalated, f"runtime SA is bound to escalated roles: {sorted(escalated)}"
    assert "roles/secretmanager.secretAccessor" in granted


def test_broad_deploy_roles_stay_behind_the_opt_out_switch(config):
    """The broad roles must only be granted inside the gated block."""
    script = _script(_step(config, "ensure-infra"))
    gate = "_GRANT_RUNTIME_DEPLOY_ROLES"
    assert gate in config["substitutions"], f"{gate} must be a declared substitution"

    guarded = re.search(
        r'if \[ "\$\{%s\}" = "true" \]; then(.*?)^\s*else\b' % gate,
        script,
        re.DOTALL | re.MULTILINE,
    )
    assert guarded, "deploy-stage roles are not wrapped in the opt-out guard"
    guarded_roles = set(re.findall(r"roles/[a-zA-Z0-9._]+", guarded.group(1)))
    assert guarded_roles == DEPLOY_STAGE_ROLES

    # None of them may also be granted unconditionally elsewhere in the step.
    outside = script.replace(guarded.group(1), "")
    for role in DEPLOY_STAGE_ROLES - {"roles/iam.serviceAccountUser"}:
        assert role not in outside, f"{role} is granted outside the guard"


def test_deployer_actas_binding_does_not_target_the_runtime_identity(config):
    """The actAs grant must name the deployer as member, not the runtime SA."""
    script = _script(_step(config, "ensure-infra"))
    for command in _iam_bindings(script):
        if "roles/iam.serviceAccountUser" in command:
            assert "--member=\"serviceAccount:$$DEPLOYER\"" in command


def test_smoke_asserts_the_health_contract(config):
    script = _script(_step(config, "smoke"))
    assert '"ok":true' in script
    assert '"service":"osa-repo-closer"' in script


def test_every_bash_step_is_syntactically_valid(config, tmp_path):
    """Catch shell syntax errors offline instead of as a bare exit 1 in a build."""
    import subprocess

    subs = config["substitutions"]
    for step in config["steps"]:
        if step.get("entrypoint") != "bash":
            continue
        script = str(step["args"][-1])
        for key, value in subs.items():
            script = script.replace("${%s}" % key, value)
        script = script.replace("$PROJECT_ID", "test-project")
        script = script.replace("$BUILD_ID", "test-build")
        script = script.replace("$$", "$")  # Cloud Build unescaping

        path = tmp_path / f"{step['id']}.sh"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{step['id']}: {result.stderr}"
