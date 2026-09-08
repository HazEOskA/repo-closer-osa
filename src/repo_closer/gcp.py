from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess


@dataclass(frozen=True)
class BuildResult:
    build_id: str
    image: str
    digest: str
    immutable_image: str


@dataclass(frozen=True)
class DeployResult:
    service: str
    region: str
    revision: str
    url: str


class GCPAdapter:
    def build(self, workspace: Path, project: str, region: str, artifact_repo: str, image_name: str, source_sha: str) -> BuildResult:
        image_base = f"{region}-docker.pkg.dev/{project}/{artifact_repo}/{image_name}"
        tag = f"{image_base}:{source_sha[:12]}"
        out = subprocess.check_output([
            "gcloud", "builds", "submit", str(workspace), "--project", project,
            "--tag", tag, "--format=json", "--quiet"
        ], text=True, timeout=2400)
        data = json.loads(out)
        build_id = data.get("id") or data.get("name", "").rsplit("/", 1)[-1]
        digest = ""
        images = data.get("results", {}).get("images", []) if isinstance(data.get("results"), dict) else []
        if images:
            digest = images[0].get("digest", "")
        if not digest or not digest.startswith("sha256:"):
            raise RuntimeError("Cloud Build nie zwrócił poprawnego immutable image digest.")
        immutable_image = f"{image_base}@{digest}"
        return BuildResult(build_id, tag, digest, immutable_image)

    def deploy(self, build: BuildResult, project: str, region: str, service: str, service_account: str | None = None) -> DeployResult:
        if not build.immutable_image or "@sha256:" not in build.immutable_image:
            raise ValueError("Deploy wymaga immutable image@sha256:digest z zatwierdzonego buildu.")
        cmd = ["gcloud", "run", "deploy", service, "--project", project, "--region", region, "--image", build.immutable_image, "--quiet", "--format=json"]
        if service_account:
            cmd += ["--service-account", service_account]
        out = subprocess.check_output(cmd, text=True, timeout=1800)
        data = json.loads(out)
        revision = data.get("status", {}).get("latestReadyRevisionName", "")
        url = data.get("status", {}).get("url", "")
        return DeployResult(service, region, revision, url)

    def verify(self, url: str, path: str = "/health") -> tuple[bool, str]:
        target = url.rstrip("/") + path
        p = subprocess.run(["curl", "-fsS", "--max-time", "20", target], capture_output=True, text=True, timeout=30)
        return p.returncode == 0, (p.stdout + p.stderr)[-4000:]
