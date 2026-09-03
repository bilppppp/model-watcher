"""Simple, robust persistent state for tracking evaluated models and baseline discovery."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional

from model_watcher.types import ModelLifecycleStatus


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    cleaned = date_str.strip().replace("_", "-")
    # Try YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", cleaned)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return None
    # Try ISO
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except Exception:
        return None


def is_recent_date(date_str: Optional[str], max_days: int = 60) -> bool:
    dt = parse_date(date_str)
    if not dt:
        return False
    now = datetime.now(timezone.utc)
    delta = (now - dt).total_seconds() / 86400.0
    return 0 <= delta <= max_days


@dataclass
class TrackedModelRecord:
    canonical_id: str
    display_name: str
    provider: str
    benchmark_first_seen: str
    release_date: Optional[str] = None
    release_confirmed: bool = False
    evaluated_at: Optional[str] = None
    status: str = ModelLifecycleStatus.SEEN.value
    report_ref: Optional[str] = None
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
            benchmark_first_seen=data.get("benchmark_first_seen") or data.get("first_seen") or datetime.now(timezone.utc).isoformat(),
            release_date=data.get("release_date"),
            release_confirmed=bool(data.get("release_confirmed", False)),
            evaluated_at=data.get("evaluated_at"),
            status=data.get("status", ModelLifecycleStatus.SEEN.value),
            report_ref=data.get("report_ref"),
            last_evidence_hash=data.get("last_evidence_hash", ""),
            re_eval_count=data.get("re_eval_count", 0),
        )


@dataclass
class WatcherState:
    version: str = "1.0"
    last_run: Optional[str] = None
    models: Dict[str, TrackedModelRecord] = field(default_factory=dict)

    def record_seen(
        self,
        canonical_id: str,
        display_name: str,
        provider: str,
        release_date: Optional[str] = None,
        release_confirmed: bool = False,
    ) -> TrackedModelRecord:
        """Records a model as known historical baseline without generating an evaluation report."""
        now_str = datetime.now(timezone.utc).isoformat()
        if canonical_id in self.models:
            rec = self.models[canonical_id]
            if release_date and not rec.release_date:
                rec.release_date = release_date
                rec.release_confirmed = release_confirmed
            return rec

        rec = TrackedModelRecord(
            canonical_id=canonical_id,
            display_name=display_name,
            provider=provider,
            benchmark_first_seen=now_str,
            release_date=release_date,
            release_confirmed=release_confirmed,
            evaluated_at=None,
            status=ModelLifecycleStatus.SEEN.value,
            report_ref=None,
            last_evidence_hash="",
            re_eval_count=0,
        )
        self.models[canonical_id] = rec
        return rec

    def should_evaluate(
        self,
        canonical_id: str,
        release_date: Optional[str] = None,
        release_confirmed: bool = False,
        force: bool = False,
    ) -> bool:
        """Determines if a candidate model qualifies for evaluation on this run.

        Separates 'new benchmark entry' from 'new model release':
        - Existing models in SEEN or MATURE are skipped.
        - Existing PROVISIONAL models are re-evaluated once ~7 days later.
        - Brand new entries must have a confirmed, recent release date to trigger unsolicited evaluation.
        """
        if force:
            return True

        if canonical_id in self.models:
            rec = self.models[canonical_id]
            if rec.status == ModelLifecycleStatus.SEEN.value:
                return False
            if rec.status == ModelLifecycleStatus.MATURE.value:
                return False
            if rec.status == ModelLifecycleStatus.PROVISIONAL.value:
                # Check if ~7 days have passed since first evaluation
                ref_time_str = rec.evaluated_at or rec.benchmark_first_seen
                ref_dt = parse_date(ref_time_str)
                if ref_dt:
                    now = datetime.now(timezone.utc)
                    days_elapsed = (now - ref_dt).total_seconds() / 86400.0
                    if days_elapsed >= 7.0 and rec.re_eval_count == 0:
                        return True
                return False
            return False

        # Brand new entry not yet in state:
        # Check if release is confirmed and recent
        if release_confirmed and release_date:
            if is_recent_date(release_date, max_days=60):
                return True
            # Older release that just appeared on benchmark: record as SEEN, don't alert
            return False

        # Release date cannot be confirmed; do not guess or generate false 'new release' alert
        return False

    def record_evaluation(
        self,
        canonical_id: str,
        display_name: str,
        provider: str,
        report_ref: str,
        release_date: Optional[str] = None,
        release_confirmed: bool = False,
        evidence_hash: str = "",
    ) -> TrackedModelRecord:
        now_str = datetime.now(timezone.utc).isoformat()

        if canonical_id in self.models:
            rec = self.models[canonical_id]
            rec.evaluated_at = now_str
            rec.status = ModelLifecycleStatus.MATURE.value
            rec.report_ref = report_ref
            rec.last_evidence_hash = evidence_hash
            rec.re_eval_count += 1
            if release_date:
                rec.release_date = release_date
                rec.release_confirmed = release_confirmed
            return rec
        else:
            rec = TrackedModelRecord(
                canonical_id=canonical_id,
                display_name=display_name,
                provider=provider,
                benchmark_first_seen=now_str,
                release_date=release_date,
                release_confirmed=release_confirmed,
                evaluated_at=now_str,
                status=ModelLifecycleStatus.PROVISIONAL.value,
                report_ref=report_ref,
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
