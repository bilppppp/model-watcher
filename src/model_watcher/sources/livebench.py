"""LiveBench official machine-readable data reader.

Prefers LiveBench 2.0 data hosted at livebench.ai/data/<YYYYMMDD>/,
with fallback to LiveBench 1.0 tables under livebench.ai/v1/ and the
livebench.github.io public/ tree (the old LiveBench/new-livebench repo
is gone and returns 404).
"""
import csv
import io
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from model_watcher.sources.base import DataSource, http_get, http_get_json
from model_watcher.types import BenchmarkEvidence, ModelMetadata, Role

logger = logging.getLogger(__name__)

_SITE = "https://livebench.ai"
_V1_GITHUB_API = "https://api.github.com/repos/LiveBench/livebench.github.io/contents/public"
_V1_RAW_BASE = "https://raw.githubusercontent.com/LiveBench/livebench.github.io/main/public"
_V2_FALLBACK_DATE = "20261014"  # known working release if JS discovery fails
_V1_FALLBACK_DATE = "2026_06_25"


def _normalize_name(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _format_display_date(date_token: str) -> str:
    """Normalize YYYYMMDD / YYYY_MM_DD / YYYY-MM-DD into YYYY-MM-DD."""
    if re.fullmatch(r"\d{8}", date_token):
        return f"{date_token[:4]}-{date_token[4:6]}-{date_token[6:8]}"
    return date_token.replace("_", "-")


_GLOBAL_LIVEBENCH_CATEGORIES: Optional[Dict[str, List[str]]] = None
_GLOBAL_LIVEBENCH_SCORES: Optional[Dict[str, Dict[str, float]]] = None
_GLOBAL_LIVEBENCH_RAW_MODELS: Optional[List[str]] = None
_GLOBAL_LIVEBENCH_DATE: Optional[str] = None
_GLOBAL_LIVEBENCH_GEN: Optional[str] = None  # "v2" or "v1"
_GLOBAL_LIVEBENCH_TABLE_URL: Optional[str] = None


class LiveBenchSource(DataSource):
    name: str = "LiveBench"
    priority: int = 0  # P0

    def __init__(self):
        self.latest_date: str = _V2_FALLBACK_DATE
        self.generation: str = "v2"
        self.table_url: str = f"{_SITE}/data/{_V2_FALLBACK_DATE}/table.csv"
        self._categories: Optional[Dict[str, List[str]]] = _GLOBAL_LIVEBENCH_CATEGORIES
        self._model_scores: Optional[Dict[str, Dict[str, float]]] = _GLOBAL_LIVEBENCH_SCORES
        self._raw_models: List[str] = _GLOBAL_LIVEBENCH_RAW_MODELS or []

    def _discover_v2_date_from_site(self) -> Optional[str]:
        """Parse livebench.ai asset-manifest + main.js for `_e=["YYYYMMDD", ...]`."""
        try:
            manifest = http_get_json(f"{_SITE}/asset-manifest.json", timeout=10)
            main_js = (manifest.get("files") or {}).get("main.js")
            if not main_js:
                entrypoints = manifest.get("entrypoints") or []
                for ep in entrypoints:
                    if ep.endswith(".js") and "main." in ep:
                        main_js = ep
                        break
            if not main_js:
                return None
            if main_js.startswith("./"):
                main_js = main_js[2:]
            js_url = f"{_SITE}/{main_js.lstrip('/')}"
            js_text = http_get(js_url, timeout=20).decode("utf-8", errors="ignore")
            m = re.search(r"_e=\[((?:\"\d{8}\",?\s*)+)\]", js_text)
            if not m:
                # broader: any quoted YYYYMMDD near data/ path usage
                dates = re.findall(r"\"(20\d{6})\"", js_text)
                dates = [d for d in dates if d.startswith("202")]
                if not dates:
                    return None
                dates = sorted(set(dates))
                return dates[-1]
            dates = re.findall(r"\"(\d{8})\"", m.group(1))
            if not dates:
                return None
            dates.sort()
            return dates[-1]
        except Exception as e:
            logger.info(f"LiveBench 2.0 JS date discovery failed: {e}")
            return None

    def _probe_v2_date(self, date_token: str) -> bool:
        url = f"{_SITE}/data/{date_token}/table.csv"
        try:
            http_get(url, timeout=10)
            return True
        except Exception:
            return False

    def _discover_v1_date(self) -> Optional[str]:
        # Prefer GitHub Contents API on livebench.github.io (replaces gone new-livebench).
        try:
            items = http_get_json(_V1_GITHUB_API, timeout=10)
            dates = []
            for item in items:
                name = item.get("name", "")
                m = re.match(r"^table_(\d{4}_\d{2}_\d{2})\.csv$", name)
                if m:
                    dates.append(m.group(1))
            if dates:
                dates.sort()
                return dates[-1]
        except Exception as e:
            logger.info(f"LiveBench 1.0 GitHub date discovery failed: {e}")

        # Site-hosted v1 fallback probe of known latest.
        if self._probe_v1_date(_V1_FALLBACK_DATE):
            return _V1_FALLBACK_DATE
        return None

    def _probe_v1_date(self, date_token: str) -> bool:
        for url in (
            f"{_SITE}/v1/table_{date_token}.csv",
            f"{_V1_RAW_BASE}/table_{date_token}.csv",
        ):
            try:
                http_get(url, timeout=10)
                return True
            except Exception:
                continue
        return False

    def _discover_latest(self) -> Tuple[str, str]:
        """Return (date_token, generation) preferring v2."""
        v2 = self._discover_v2_date_from_site()
        if v2 and self._probe_v2_date(v2):
            return v2, "v2"
        if self._probe_v2_date(_V2_FALLBACK_DATE):
            logger.info(
                f"LiveBench JS discovery missed; using verified 2.0 release {_V2_FALLBACK_DATE}"
            )
            return _V2_FALLBACK_DATE, "v2"

        v1 = self._discover_v1_date()
        if v1:
            logger.info(f"LiveBench falling back to 1.0 release {v1}")
            return v1, "v1"

        logger.info(
            f"LiveBench dynamic discovery failed; hard-falling back to {_V2_FALLBACK_DATE}"
        )
        return _V2_FALLBACK_DATE, "v2"

    def _urls_for(self, date_token: str, generation: str) -> Tuple[str, str]:
        if generation == "v2":
            base = f"{_SITE}/data/{date_token}"
            return f"{base}/categories.json", f"{base}/table.csv"
        # v1: try site first, raw github second (caller retries on fetch error)
        return (
            f"{_SITE}/v1/categories_{date_token}.json",
            f"{_SITE}/v1/table_{date_token}.csv",
        )

    def _v1_github_urls(self, date_token: str) -> Tuple[str, str]:
        return (
            f"{_V1_RAW_BASE}/categories_{date_token}.json",
            f"{_V1_RAW_BASE}/table_{date_token}.csv",
        )

    def _load_data(self) -> None:
        global \
            _GLOBAL_LIVEBENCH_CATEGORIES, \
            _GLOBAL_LIVEBENCH_SCORES, \
            _GLOBAL_LIVEBENCH_RAW_MODELS, \
            _GLOBAL_LIVEBENCH_DATE, \
            _GLOBAL_LIVEBENCH_GEN, \
            _GLOBAL_LIVEBENCH_TABLE_URL
        if _GLOBAL_LIVEBENCH_SCORES is not None:
            self._categories = _GLOBAL_LIVEBENCH_CATEGORIES
            self._model_scores = _GLOBAL_LIVEBENCH_SCORES
            self._raw_models = _GLOBAL_LIVEBENCH_RAW_MODELS or []
            if _GLOBAL_LIVEBENCH_DATE:
                self.latest_date = _GLOBAL_LIVEBENCH_DATE
            if _GLOBAL_LIVEBENCH_GEN:
                self.generation = _GLOBAL_LIVEBENCH_GEN
            if _GLOBAL_LIVEBENCH_TABLE_URL:
                self.table_url = _GLOBAL_LIVEBENCH_TABLE_URL
            return

        date_token, generation = self._discover_latest()
        self.latest_date = date_token
        self.generation = generation
        cat_url, table_url = self._urls_for(date_token, generation)
        self.table_url = table_url

        # Categories
        try:
            cat_bytes = http_get(cat_url, timeout=15)
            self._categories = json.loads(cat_bytes.decode("utf-8"))
            _GLOBAL_LIVEBENCH_CATEGORIES = self._categories
        except Exception as e:
            if generation == "v1":
                try:
                    alt_cat, _ = self._v1_github_urls(date_token)
                    cat_bytes = http_get(alt_cat, timeout=15)
                    self._categories = json.loads(cat_bytes.decode("utf-8"))
                    _GLOBAL_LIVEBENCH_CATEGORIES = self._categories
                    cat_url = alt_cat
                except Exception as e2:
                    logger.error(f"Failed to fetch LiveBench categories: {e}; alt: {e2}")
                    self._categories = {}
            else:
                logger.error(f"Failed to fetch LiveBench categories: {e}")
                self._categories = {}

        # Table
        try:
            table_bytes = http_get(table_url, timeout=15)
        except Exception as e:
            if generation == "v1":
                try:
                    _, alt_table = self._v1_github_urls(date_token)
                    table_bytes = http_get(alt_table, timeout=15)
                    table_url = alt_table
                    self.table_url = alt_table
                except Exception as e2:
                    logger.error(f"Failed to fetch LiveBench table: {e}; alt: {e2}")
                    self._model_scores = {}
                    _GLOBAL_LIVEBENCH_SCORES = {}
                    _GLOBAL_LIVEBENCH_RAW_MODELS = []
                    _GLOBAL_LIVEBENCH_DATE = date_token
                    _GLOBAL_LIVEBENCH_GEN = generation
                    _GLOBAL_LIVEBENCH_TABLE_URL = table_url
                    return
            else:
                logger.error(f"Failed to fetch LiveBench table: {e}")
                self._model_scores = {}
                _GLOBAL_LIVEBENCH_SCORES = {}
                _GLOBAL_LIVEBENCH_RAW_MODELS = []
                _GLOBAL_LIVEBENCH_DATE = date_token
                _GLOBAL_LIVEBENCH_GEN = generation
                _GLOBAL_LIVEBENCH_TABLE_URL = table_url
                return

        try:
            csv_text = table_bytes.decode("utf-8")
            reader = csv.DictReader(io.StringIO(csv_text))

            scores: Dict[str, Dict[str, float]] = {}
            for row in reader:
                model_name = row.get("model", "").strip()
                if not model_name:
                    continue
                self._raw_models.append(model_name)
                scores[model_name] = {}

                # Compute category averages across mapped subtask columns
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
            _GLOBAL_LIVEBENCH_SCORES = scores
            _GLOBAL_LIVEBENCH_RAW_MODELS = self._raw_models
            _GLOBAL_LIVEBENCH_DATE = date_token
            _GLOBAL_LIVEBENCH_GEN = generation
            _GLOBAL_LIVEBENCH_TABLE_URL = table_url
            logger.info(
                f"LiveBench loaded {generation} release {date_token} "
                f"({len(scores)} models) from {table_url}"
            )
        except Exception as e:
            logger.error(f"Failed to parse LiveBench table: {e}")
            self._model_scores = {}
            _GLOBAL_LIVEBENCH_SCORES = {}
            _GLOBAL_LIVEBENCH_RAW_MODELS = []
            _GLOBAL_LIVEBENCH_DATE = date_token
            _GLOBAL_LIVEBENCH_GEN = generation
            _GLOBAL_LIVEBENCH_TABLE_URL = table_url

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
                    first_seen=_format_display_date(self.latest_date),
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

    def _category_for_role(self, role: Role) -> Optional[str]:
        if role == Role.REASONER:
            return "Reasoning"
        if role == Role.CODER:
            return "Coding"
        if role == Role.ANALYST:
            return "Data Analysis"
        if role == Role.AGENT:
            # 2.0 renamed Agentic Coding → Long Agentic
            cats = self._categories or {}
            if "Long Agentic" in cats:
                return "Long Agentic"
            if "Agentic Coding" in cats:
                return "Agentic Coding"
            return "Long Agentic"
        # Planner, Reviewer, Multimodal are not directly evaluated in LiveBench
        return None

    def get_evidence(
        self,
        challenger: str,
        incumbent: str,
        role: Role,
    ) -> Optional[BenchmarkEvidence]:
        self._load_data()

        category = self._category_for_role(role)
        if not category:
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
            version=_format_display_date(self.latest_date),
            score_challenger=round(c_score, 2),
            score_incumbent=round(i_score, 2) if i_score is not None else None,
            display_metric="%",
            harness="official public leaderboard",
            url=self.table_url,
            confidence=0.85,
            known_uncertainty="LiveBench category average across contamination-resistant questions",
        )
