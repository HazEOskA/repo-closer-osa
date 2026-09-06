from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac

from .canonical import canonical_json, sha256_hex
from .domain import ApprovalRecord, Run


class ApprovalAuthority:
    def __init__(self, secret: str):
        if len(secret) < 24:
            raise ValueError("Approval secret musi mieć co najmniej 24 znaki.")
        self.secret = secret.encode()

    def target_hash(self, run: Run, action: str, target: dict) -> str:
        envelope = {
            "run_id": run.run_id,
            "action": action,
            "repo": run.repository.slug if run.repository else None,
            "base_sha": run.base_sha,
            "plan_hash": run.repair_plan.plan_hash if run.repair_plan else None,
            "target": target,
        }
        return sha256_hex(envelope)

    def issue(self, run: Run, action: str, actor: str, target: dict, ttl_minutes: int = 60) -> ApprovalRecord:
        issued = datetime.now(timezone.utc)
        expires = issued + timedelta(minutes=ttl_minutes)
        target_hash = self.target_hash(run, action, target)
        payload = {
            "action": action,
            "actor": actor,
            "target_hash": target_hash,
            "issued_at": issued.isoformat(),
            "expires_at": expires.isoformat(),
        }
        sig = hmac.new(self.secret, canonical_json(payload), hashlib.sha256).hexdigest()
        return ApprovalRecord(signature=sig, **payload)

    def verify(self, run: Run, record: ApprovalRecord, action: str, target: dict) -> bool:
        if record.action != action:
            return False
        if datetime.fromisoformat(record.expires_at) <= datetime.now(timezone.utc):
            return False
        target_hash = self.target_hash(run, action, target)
        if not hmac.compare_digest(record.target_hash, target_hash):
            return False
        payload = {
            "action": record.action,
            "actor": record.actor,
            "target_hash": record.target_hash,
            "issued_at": record.issued_at,
            "expires_at": record.expires_at,
        }
        expected = hmac.new(self.secret, canonical_json(payload), hashlib.sha256).hexdigest()
        return hmac.compare_digest(record.signature, expected)
