"""LiveBench official machine-readable data reader."""
import csv
import io
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from model_watcher.sources.base import DataSource, http_get, http_get_json
from model_watcher.types import BenchmarkEvidence, ModelMetadata, Role

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


class LiveBenchSource(DataSource):
    name: str = "LiveBench"
    priority: int = 0  # P0

    def __init__(self):
        self.latest_date: str = "2026_06_25"
        self._categories: Optional[Dict[str, List[str]]] = None
        self._model_scores: Optional[Dict[str, Dict[str, float]]] = None
        self._raw_models: List[str] = []

    def _discover_latest_date(self) -> str:
        api_url = "https://api.github.com/repos/LiveBench/new-livebench/contents/public"
        try:
            items = http_get_json(api_url, timeout=10)
            dates = []
            for item in items:
                name = item.get("name", "")
                m = re.match(r"^table_(\d{4}_\d{2}_\d{2})\.csv$", name)
                if m:
                    dates.append(m.group(1))
            if dates:
                dates.sort()
                self.latest_date = dates[-1]
        except Exception as e:
            logger.info(f"LiveBench dynamic date discovery fell back to verified release {self.latest_date}: {e}")
        return self.latest_date

    def _load_data(self) -> None:
        if self._model_scores is not None:
            return

        self._discover_latest_date()
        cat_url = f"https://raw.githubusercontent.com/LiveBench/new-livebench/main/public/categories_{self.latest_date}.json"
        table_url = f"https://raw.githubusercontent.com/LiveBench/new-livebench/main/public/table_{self.latest_date}.csv"

        try:
            cat_bytes = http_get(cat_url, timeout=15)
            self._categories = json.loads(cat_bytes.decode("utf-8"))
        except Exception as e:
            logger.error(f"Failed to fetch LiveBench categories: {e}")
            self._categories = {}

        try:
            table_bytes = http_get(table_url, timeout=15)
            csv_text = table_bytes.decode("utf-8")
            reader = csv.DictReader(io.StringIO(csv_text))

            scores: Dict[str, Dict[str, float]] = {}
            for row in reader:
                model_name = row.get("model", "").strip()
                if not model_name:
                    continue
                self._raw_models.append(model_name)
                scores[model_name] = {}

                # Compute category averages
                for category, subtasks in (self._categories or {}).items():
                    subtask_vals = []
                    for st in subtasks:
                        val_str = row.get(st)
                        if val_str is not None and val_str != "":
                            try:
                                subtask_vals.append(float(val_str))
                            except ValueError:
                                pass
                    if subtask_vals:
                        scores[model_name][category] = sum(subtask_vals) / len(subtask_vals)

            self._model_scores = scores
        except Exception as e:
            logger.error(f"Failed to fetch LiveBench table: {e}")
            self._model_scores = {}

    def discover_models(self) -> List[ModelMetadata]:
        self._load_data()
        results = []
        for raw_name in self._raw_models:
            # Infer provider
            provider = "Unknown"
            low = raw_name.lower()
            if "claude" in low or "anthropic" in low:
                provider = "Anthropic"
            elif "gpt" in low or "openai" in low or "o1" in low or "o3" in low:
                provider = "OpenAI"
            elif "gemini" in low or "google" in low:
                provider = "Google"
            elif "deepseek" in low:
                provider = "DeepSeek"
            elif "meta" in low or "llama" in low:
                provider = "Meta"

            scores = (self._model_scores or {}).get(raw_name, {})
            results.append(
                ModelMetadata(
                    canonical_id=raw_name,
                    display_name=raw_name,
                    provider=provider,
                    headline_indices={k: round(v, 2) for k, v in scores.items()},
                    first_seen=self.latest_date.replace("_", "-"),
                    raw_source=self.name,
                )
            )
        return results

    def _find_matching_model_key(self, target: str) -> Optional[str]:
        if not self._model_scores:
            return None

        norm_target = _normalize_name(target)
        # 1. Exact match
        for k in self._model_scores:
            if _normalize_name(k) == norm_target:
                return k

        # 2. Substring containment match
        candidates = []
        for k in self._model_scores:
            norm_k = _normalize_name(k)
            if norm_target in norm_k or norm_k in norm_target:
                candidates.append(k)

        if candidates:
            # Return shortest or most relevant candidate
            candidates.sort(key=lambda x: len(x))
            return candidates[0]

        return None

    def get_evidence(
        self,
        challenger: str,
        incumbent: str,
        role: Role,
    ) -> Optional[BenchmarkEvidence]:
        self._load_data()

        # Map role to category
        category = None
        if role == Role.REASONER:
            category = "Reasoning"
        elif role == Role.CODER:
            category = "Coding"
        elif role == Role.ANALYST:
            category = "Data Analysis"
        elif role == Role.AGENT:
            category = "Agentic Coding"
        else:
            # Planner, Reviewer, Multimodal are not directly evaluated in LiveBench
            return None

        challenger_key = self._find_matching_model_key(challenger)
        incumbent_key = self._find_matching_model_key(incumbent)

        if not challenger_key:
            return None

        c_scores = (self._model_scores or {}).get(challenger_key, {})
        c_score = c_scores.get(category)
        if c_score is None:
            return None

        i_score = None
        if incumbent_key:
            i_scores = (self._model_scores or {}).get(incumbent_key, {})
            i_score = i_scores.get(category)

        return BenchmarkEvidence(
            source=self.name,
            benchmark=f"LiveBench ({category})",
            version=self.latest_date,
            score_challenger=round(c_score, 2),
            score_incumbent=round(i_score, 2) if i_score is not None else None,
            display_metric="%",
            harness="official public leaderboard",
            url=f"https://github.com/LiveBench/new-livebench/blob/main/public/table_{self.latest_date}.csv",
            confidence=0.85,
            known_uncertainty="LiveBench category average across contamination-resistant questions",
        )
