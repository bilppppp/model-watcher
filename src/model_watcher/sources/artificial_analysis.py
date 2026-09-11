"""Artificial Analysis official Data API v2 reader."""
import logging
import os
import re
from typing import Any, Dict, List, Optional

from model_watcher.sources.base import DataSource, http_get_json
from model_watcher.types import BenchmarkEvidence, ModelMetadata, ReleaseEvidenceLevel, Role

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


_GLOBAL_AA_MODELS: Optional[List[Dict[str, Any]]] = None


class ArtificialAnalysisSource(DataSource):
    name: str = "Artificial Analysis"
    priority: int = 1  # P1

    BASE_URL = "https://artificialanalysis.ai/api/v2"
    FREE_ENDPOINT = "/language/models/free"
    MAX_PAGES: int = 50

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY", "")
        self._cached_models: Optional[List[Dict[str, Any]]] = _GLOBAL_AA_MODELS
        self._fetch_complete: bool = (_GLOBAL_AA_MODELS is not None)

    @property
    def is_complete(self) -> bool:
        return self._fetch_complete

    def _load_data(self) -> None:
        global _GLOBAL_AA_MODELS
        if _GLOBAL_AA_MODELS is not None:
            self._cached_models = _GLOBAL_AA_MODELS
            self._fetch_complete = True
            return

        if not self.api_key:
            logger.info("ARTIFICIAL_ANALYSIS_API_KEY not set. Skipping live AA API call.")
            self._cached_models = []
            _GLOBAL_AA_MODELS = []
            self._fetch_complete = True
            return

        url_base = f"{self.BASE_URL}{self.FREE_ENDPOINT}"
        headers = {"x-api-key": self.api_key}

        all_items: List[Dict[str, Any]] = []
        seen_keys = set()
        page = 1

        try:
            while page <= self.MAX_PAGES:
                url = f"{url_base}?page={page}"
                data = http_get_json(url, headers=headers, timeout=15)
                if not data or not isinstance(data, dict):
                    raise ValueError(f"Invalid response format at page {page}")

                items = data.get("data", [])
                for item in items:
                    dedupe_key = item.get("id") or item.get("slug") or item.get("name")
                    if dedupe_key and dedupe_key in seen_keys:
                        continue
                    if dedupe_key:
                        seen_keys.add(dedupe_key)
                    all_items.append(item)

                pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
                has_more = pagination.get("has_more") if "has_more" in pagination else data.get("has_more")
                total_pages = pagination.get("total_pages") if "total_pages" in pagination else data.get("total_pages")

                if has_more is False:
                    break
                if total_pages is not None and page >= total_pages:
                    break
                if not items:
                    break
                if page >= self.MAX_PAGES:
                    raise RuntimeError(
                        f"Artificial Analysis pagination reached MAX_PAGES ({self.MAX_PAGES}) "
                        f"while more pages remain (has_more={has_more}, total_pages={total_pages}). Fetch incomplete."
                    )
                page += 1

            self._cached_models = all_items
            _GLOBAL_AA_MODELS = all_items
            self._fetch_complete = True
        except Exception as e:
            logger.warning(f"Failed to fetch Artificial Analysis models (failed at page {page}): {e}")
            self._cached_models = []
            _GLOBAL_AA_MODELS = None
            self._fetch_complete = False

    def discover_models(self) -> List[ModelMetadata]:
        self._load_data()
        if not self._fetch_complete and self.api_key:
            logger.warning("Artificial Analysis fetch failed or incomplete; returning empty results.")
            return []
        results = []
        for item in self._cached_models or []:
            name = item.get("name", "")
            slug = item.get("slug") or item.get("id") or ""
            creator = (item.get("model_creator") or {}).get("name") or item.get("creator") or "Unknown"
            rel_date = item.get("release_date")
            pricing = item.get("pricing") or {}
            perf = item.get("performance") or {}
            evals = item.get("evaluations") or {}

            meta = ModelMetadata(
                canonical_id=slug or name.lower().replace(" ", "-"),
                display_name=name,
                provider=creator,
                release_date=rel_date,
                release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value if rel_date else ReleaseEvidenceLevel.OBSERVED_ONLY.value,
                release_confirmed=bool(rel_date),
                benchmark_first_seen=rel_date or "",
                input_price_per_m=pricing.get("price_1m_input_tokens"),
                output_price_per_m=pricing.get("price_1m_output_tokens"),
                output_tokens_per_sec=perf.get("median_output_tokens_per_second"),
                time_to_first_token_sec=perf.get("median_time_to_first_token_seconds"),
                headline_indices={
                    "aa_intelligence_index": evals.get("artificial_analysis_intelligence_index"),
                    "aa_coding_index": evals.get("artificial_analysis_coding_index"),
                    "aa_agentic_index": evals.get("artificial_analysis_agentic_index"),
                },
                first_seen=rel_date or "",
                raw_source=self.name,
            )
            results.append(meta)
        return results

    def _find_model(self, target: str) -> Optional[Dict[str, Any]]:
        self._load_data()
        norm_target = _normalize_name(target)
        for item in self._cached_models or []:
            name = item.get("name", "")
            slug = item.get("slug", "")
            if norm_target == _normalize_name(slug) or norm_target == _normalize_name(name):
                return item
            if norm_target in _normalize_name(slug) or _normalize_name(slug) in norm_target:
                return item
        return None

    def get_evidence(
        self,
        challenger: str,
        incumbent: str,
        role: Role,
    ) -> Optional[BenchmarkEvidence]:
        metric_key = None
        bench_name = None
        if role == Role.CODER:
            metric_key = "artificial_analysis_coding_index"
            bench_name = "Artificial Analysis Coding Index"
        elif role == Role.AGENT:
            metric_key = "artificial_analysis_agentic_index"
            bench_name = "Artificial Analysis Agentic Index"
        elif role == Role.REASONER:
            metric_key = "artificial_analysis_intelligence_index"
            bench_name = "Artificial Analysis Intelligence Index"
        else:
            return None

        c_item = self._find_model(challenger)
        if not c_item:
            return None

        c_evals = c_item.get("evaluations") or {}
        c_score = c_evals.get(metric_key)
        if c_score is None:
            return None

        i_score = None
        i_item = self._find_model(incumbent)
        if i_item:
            i_evals = i_item.get("evaluations") or {}
            i_score = i_evals.get(metric_key)

        return BenchmarkEvidence(
            source=self.name,
            benchmark=bench_name,
            version="v2",
            score_challenger=round(c_score, 1),
            score_incumbent=round(i_score, 1) if i_score is not None else None,
            display_metric="Index",
            harness="Artificial Analysis Independent Benchmark Suite",
            url="https://artificialanalysis.ai",
            confidence=0.80,
            known_uncertainty="Composite index computed across independent test harness runs",
        )
