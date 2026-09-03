"""Simple, robust persistent state for tracking evaluated models."""
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from model_watcher.types import ModelLifecycleStatus


@dataclass
class TrackedModelRecord:
    canonical_id: str
    display_name: str
    provider: str
    first_seen: str
    evaluated_at: str
    status: str  # "NEW", "PROVISIONAL", "MATURE"
    report_ref: Optional[str] = None
    release_date: Optional[str] = None
    last_evidence_hash: str = ""
    re_eval_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackedModelRecord":
        return cls(
            canonical_id=data["canonical_id"],
            display_name=data.get("display_name", data["canonical_id"]),
            provider=data.get("provider", "Unknown"),
            first_seen=data.get("first_seen", datetime.now(timezone.utc).isoformat()),
            evaluated_at=data.get("evaluated_at", datetime.now(timezone.utc).isoformat()),
            status=data.get("status", ModelLifecycleStatus.PROVISIONAL.value),
            report_ref=data.get("report_ref"),
            release_date=data.get("release_date"),
            last_evidence_hash=data.get("last_evidence_hash", ""),
            re_eval_count=data.get("re_eval_count", 0),
        )


@dataclass
class WatcherState:
    version: str = "1.0"
    last_run: Optional[str] = None
    models: Dict[str, TrackedModelRecord] = field(default_factory=dict)

    def should_evaluate(self, canonical_id: str, evidence_hash: str = "", force: bool = False) -> bool:
        """Determines if a model needs evaluation on this run."""
        if force:
            return True

        if canonical_id not in self.models:
            # First time seen: evaluate immediately (PROVISIONAL)
            return True

        record = self.models[canonical_id]
        if record.status == ModelLifecycleStatus.MATURE.value:
            # Mature model: do not re-evaluate
            return False

        if record.status == ModelLifecycleStatus.PROVISIONAL.value:
            # Check if ~7 days have passed since first_seen
            try:
                first_seen_dt = datetime.fromisoformat(record.first_seen.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_since_first = (now - first_seen_dt).total_seconds() / 86400.0

                if days_since_first >= 7.0 and record.re_eval_count == 0:
                    # Eligible for one mature review
                    return True
            except Exception:
                pass

            # If evidence has significantly changed, allow re-eval
            if evidence_hash and record.last_evidence_hash and evidence_hash != record.last_evidence_hash:
                return True

            # Otherwise, skip
            return False

        return False

    def record_evaluation(
        self,
        canonical_id: str,
        display_name: str,
        provider: str,
        report_ref: str,
        release_date: Optional[str] = None,
        evidence_hash: str = "",
    ) -> TrackedModelRecord:
        now_str = datetime.now(timezone.utc).isoformat()

        if canonical_id in self.models:
            rec = self.models[canonical_id]
            # Transition to MATURE after re-evaluation
            rec.evaluated_at = now_str
            rec.status = ModelLifecycleStatus.MATURE.value
            rec.report_ref = report_ref
            rec.last_evidence_hash = evidence_hash
            rec.re_eval_count += 1
            return rec
        else:
            rec = TrackedModelRecord(
                canonical_id=canonical_id,
                display_name=display_name,
                provider=provider,
                first_seen=now_str,
                evaluated_at=now_str,
                status=ModelLifecycleStatus.PROVISIONAL.value,
                report_ref=report_ref,
                release_date=release_date,
                last_evidence_hash=evidence_hash,
                re_eval_count=0,
            )
            self.models[canonical_id] = rec
            return rec

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "last_run": self.last_run,
            "models": {k: v.to_dict() for k, v in self.models.items()},
        }


DEFAULT_STATE_PATH = Path("state.json")


def load_state(path: Path = DEFAULT_STATE_PATH) -> WatcherState:
    if not path.exists():
        return WatcherState()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # Corrupted state backup
        backup_path = path.with_suffix(".corrupted.bak")
        path.rename(backup_path)
        print(f"[WARN] Failed to load state.json ({e}). Moved to {backup_path}, initialized fresh state.")
        return WatcherState()

    models = {}
    for k, v in data.get("models", {}).items():
        try:
            models[k] = TrackedModelRecord.from_dict(v)
        except Exception:
            continue

    return WatcherState(
        version=str(data.get("version", "1.0")),
        last_run=data.get("last_run"),
        models=models,
    )


def save_state(state: WatcherState, path: Path = DEFAULT_STATE_PATH) -> None:
    """Atomic write to prevent corruption during unexpected crashes."""
    state.last_run = datetime.now(timezone.utc).isoformat()
    temp_path = path.with_suffix(".tmp")

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)

    os.replace(temp_path, path)
