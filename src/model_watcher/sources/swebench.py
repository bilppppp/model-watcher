"""SWE-bench official machine-readable leaderboard reader."""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from model_watcher.sources.base import DataSource, http_get
from model_watcher.types import BenchmarkEvidence, ModelMetadata, ReleaseEvidenceLevel, Role

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


_GLOBAL_SWEBENCH_RESULTS: Optional[List[Dict[str, Any]]] = None


class SWEBenchSource(DataSource):
    name: str = "SWE-bench"
    priority: int = 0  # P0

    def __init__(self):
        self._raw_data: Optional[Dict[str, Any]] = None
        self._verified_results: Optional[List[Dict[str, Any]]] = _GLOBAL_SWEBENCH_RESULTS

    def _load_data(self) -> None:
        global _GLOBAL_SWEBENCH_RESULTS
        if _GLOBAL_SWEBENCH_RESULTS is not None:
            self._verified_results = _GLOBAL_SWEBENCH_RESULTS
            return

        url = "https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json"
        try:
            raw_bytes = http_get(url, timeout=15)
            self._raw_data = json.loads(raw_bytes.decode("utf-8"))
            leaderboards = self._raw_data.get("leaderboards", [])
            for lb in leaderboards:
                if lb.get("name") == "Verified":
                    self._verified_results = lb.get("results", [])
                    break
            if self._verified_results is None:
                self._verified_results = []
            _GLOBAL_SWEBENCH_RESULTS = self._verified_results
        except Exception as e:
            logger.error(f"Failed to fetch SWE-bench leaderboards.json: {e}")
            self._verified_results = []
            _GLOBAL_SWEBENCH_RESULTS = []

    @staticmethod
    def _is_ensemble_entry(r: Dict[str, Any]) -> bool:
        display = (r.get("model_display") or "").strip().lower()
        if display in ("multiple", "ensemble", "various", "multi-agent") or display.startswith("multiple"):
            return True
        tags = r.get("tags", [])
        model_tags = [t for t in tags if t.lower().startswith("model:")]
        if len(model_tags) > 1:
            return True
        return False

    def discover_models(self) -> List[ModelMetadata]:
        self._load_data()
        discovered = {}
        for r in self._verified_results or []:
            if self._is_ensemble_entry(r):
                continue
            model_display = r.get("model_display") or r.get("name", "")
            model_org = r.get("model_org", "Unknown")
            resolved = r.get("resolved")
            # In SWE-bench schema: 'model_release_date' is actual model release; 'date' is benchmark submission date
            model_rel_date = r.get("model_release_date")
            submission_date = r.get("date")

            canon = _normalize_name(model_display)
            if not canon or canon == "multiple":
                continue

            level = ReleaseEvidenceLevel.CONFIRMED.value if model_rel_date else ReleaseEvidenceLevel.OBSERVED_ONLY.value

            if canon not in discovered or (resolved and resolved > (discovered[canon].headline_indices.get("swe_bench_verified") or 0)):
                discovered[canon] = ModelMetadata(
                    canonical_id=model_display.lower().replace(" ", "-"),
                    display_name=model_display,
                    provider=model_org,
                    release_date=model_rel_date,
                    release_evidence_level=level,
                    release_confirmed=bool(model_rel_date),
                    benchmark_first_seen=submission_date or "",
                    headline_indices={"swe_bench_verified": resolved},
                    first_seen=submission_date or "",
                    raw_source=self.name,
                )
        return list(discovered.values())

    def _find_best_result(self, model_name: str) -> Optional[Dict[str, Any]]:
        norm_target = _normalize_name(model_name)
        if not norm_target:
            return None

        best = None
        best_score = -1.0

        for r in self._verified_results or []:
            # Disallow ensemble / multi-agent submissions as single model evidence
            if self._is_ensemble_entry(r):
                continue

            name = (r.get("model_display") or r.get("name", "")).strip()
            norm_name = _normalize_name(name)
            if not norm_name or norm_name == "multiple":
                continue

            # Prioritize matching model_display / explicit single model identity
            matched = False
            if norm_target == norm_name:
                matched = True
            elif norm_target in norm_name or norm_name in norm_target:
                if len(norm_target) >= 4 and len(norm_name) >= 4:
                    matched = True
                elif norm_target == norm_name:
                    matched = True

            # If not matched on display name, check if there is a single explicit Model tag
            if not matched:
                model_tags = [t for t in r.get("tags", []) if t.lower().startswith("model:")]
                if len(model_tags) == 1:
                    tag_model = model_tags[0].split(":", 1)[1].strip()
                    norm_tag_model = _normalize_name(tag_model)
                    if norm_target == norm_tag_model or (len(norm_target) >= 5 and norm_target in norm_tag_model):
                        matched = True

            if matched:
                score = float(r.get("resolved") or 0.0)
                if score > best_score:
                    best_score = score
                    best = r

        return best

    def get_evidence(
        self,
        challenger: str,
        incumbent: str,
        role: Role,
    ) -> Optional[BenchmarkEvidence]:
        if role != Role.CODER:
            return None

        self._load_data()
        c_res = self._find_best_result(challenger)
        if not c_res:
            return None

        i_res = self._find_best_result(incumbent)

        c_score = float(c_res.get("resolved", 0.0))
        i_score = float(i_res.get("resolved", 0.0)) if i_res else None
        c_agent = c_res.get("agent", "Unknown Agent")

        uncertainty = ""
        if i_res and c_res.get("agent") != i_res.get("agent"):
            uncertainty = f"Different harness: challenger on {c_agent}, incumbent on {i_res.get('agent')}"

        return BenchmarkEvidence(
            source=self.name,
            benchmark="SWE-bench Verified",
            version="verified-v1",
            score_challenger=round(c_score, 1),
            score_incumbent=round(i_score, 1) if i_score is not None else None,
            display_metric="% resolved",
            harness=c_agent,
            url="https://www.swebench.com",
            confidence=0.85 if not uncertainty else 0.75,
            known_uncertainty=uncertainty or "Official verified benchmark submission",
        )
