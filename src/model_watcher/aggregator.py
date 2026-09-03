"""Model discovery and evidence aggregation across structured data sources."""
import datetime
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from model_watcher.sources.artificial_analysis import ArtificialAnalysisSource
from model_watcher.sources.harbor import HarborSource
from model_watcher.sources.livebench import LiveBenchSource
from model_watcher.sources.lmms_eval import LMMsEvalSource
from model_watcher.sources.swebench import SWEBenchSource
from model_watcher.state import WatcherState
from model_watcher.types import (
    AmbiguousModelError,
    BenchmarkEvidence,
    ModelMetadata,
    ModelNotFoundError,
    ReleaseEvidenceLevel,
    Role,
)

logger = logging.getLogger(__name__)

OUT_OF_SCOPE_PATTERNS = [
    r"embed",
    r"embedding",
    r"rerank",
    r"whisper",
    r"tts",
    r"speech",
    r"flux",
    r"stable-diffusion",
    r"sdxl",
    r"midjourney",
    r"dall-e",
    r"suno",
    r"udio",
    r"bge-",
    r"gte-",
    r"e5-",
    r"instructor-",
    r"-0\.5b",
    r"-0\.1b",
]

TRUSTED_PROVIDERS = {
    "anthropic",
    "openai",
    "google",
    "meta",
    "deepseek",
    "mistral",
    "qwen",
    "alibaba",
    "zhipu",
    "glm",
    "moonshot",
    "kimi",
    "xai",
    "cohere",
}

KNOWN_VENDOR_PREFIXES = (
    "claude-",
    "gpt-",
    "o1-",
    "o3-",
    "o4-",
    "gemini-",
    "deepseek-",
    "qwen",
    "glm-",
    "grok-",
    "llama-",
    "mistral-",
    "devstral-",
)


def is_in_tracking_scope(model: ModelMetadata) -> bool:
    name_low = model.canonical_id.lower() + " " + model.display_name.lower()
    for pat in OUT_OF_SCOPE_PATTERNS:
        if re.search(pat, name_low):
            return False
    return True


def is_trusted_provider(provider: Optional[str], canonical_id: str) -> bool:
    p = (provider or "").lower()
    cid = (canonical_id or "").lower()
    if any(tp in p for tp in TRUSTED_PROVIDERS):
        return True
    if any(cid.startswith(pref) for pref in KNOWN_VENDOR_PREFIXES):
        return True
    return False


def extract_date_from_name(name: Optional[str]) -> Optional[str]:
    """Extracts explicit version/release date formatted in model name."""
    if not name:
        return None
    m1 = re.search(r"(202[3-9])-([01][0-9])-([0-3][0-9])", name)
    if m1:
        return f"{m1.group(1)}-{m1.group(2)}-{m1.group(3)}"
    m2 = re.search(r"(202[3-9])([01][0-9])([0-3][0-9])", name)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    return None


_HF_CACHE: Dict[str, Optional[str]] = {}


def query_huggingface_repository_created_at(model_id: str) -> Optional[str]:
    """Queries official Hugging Face Hub for repo creation date.

    Note per Hugging Face documentation:
    'createdAt' reflects repository creation on Hub, NOT official model release date.
    Saved strictly as repository_first_seen (OBSERVED_ONLY).
    """
    clean_id = re.sub(r"-(high|medium|low|xhigh|thinking|preview|instruct|fp8|chat)$", "", model_id.lower())
    if clean_id in _HF_CACHE:
        return _HF_CACHE[clean_id]

    search_term = clean_id.split("-")[0] if "-" in clean_id else clean_id
    if len(search_term) < 3:
        search_term = clean_id

    url = f"https://huggingface.co/api/models?search={urllib.parse.quote(search_term)}&limit=3"
    req = urllib.request.Request(url, headers={"User-Agent": "ModelWatcher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for item in data:
                item_id = item.get("id", "").lower()
                created_at = item.get("createdAt")
                if created_at and (clean_id in item_id or item_id in clean_id):
                    res = created_at[:10]
                    _HF_CACHE[clean_id] = res
                    return res
    except Exception as e:
        logger.debug(f"HF model query skipped for {model_id}: {e}")
    _HF_CACHE[clean_id] = None
    return None


def confirm_release_fallback(model: ModelMetadata) -> None:
    """Classifies release evidence level: CONFIRMED, TRUSTED, INFERRED, or OBSERVED_ONLY.

    - CONFIRMED / TRUSTED: already confirmed by official source or AA
    - INFERRED: trusted provider canonical model identifier contains explicit date
    - OBSERVED_ONLY: HF repo createdAt, benchmark submission date
    """
    # If already confirmed or trusted, keep existing high-confidence provenance immediately!
    if model.release_evidence_level in (ReleaseEvidenceLevel.CONFIRMED.value, ReleaseEvidenceLevel.TRUSTED.value):
        return

    # Check if trusted provider's canonical model ID explicitly includes version date
    if is_trusted_provider(model.provider, model.canonical_id):
        date_in_name = extract_date_from_name(model.canonical_id) or extract_date_from_name(model.display_name)
        if date_in_name:
            model.release_date = date_in_name
            model.release_evidence_level = ReleaseEvidenceLevel.INFERRED.value
            model.release_confirmed = False  # Inferred, not confirmed
            return

    # Query HF repo createdAt as repository_first_seen (OBSERVED_ONLY evidence)
    if not model.repository_first_seen:
        hf_created = query_huggingface_repository_created_at(model.canonical_id)
        if hf_created:
            model.repository_first_seen = hf_created

    # 3. Otherwise, remains OBSERVED_ONLY; do NOT fabricate release date
    model.release_evidence_level = ReleaseEvidenceLevel.OBSERVED_ONLY.value


class ModelAggregator:
    def __init__(self, sources: Optional[List] = None):
        if sources is not None:
            self.sources = sources
        else:
            self.sources = [
                LiveBenchSource(),
                SWEBenchSource(),
                HarborSource(),
                ArtificialAnalysisSource(),
                LMMsEvalSource(),
            ]

    def discover_all_candidates(self) -> List[ModelMetadata]:
        all_models: Dict[str, ModelMetadata] = {}

        for src in self.sources:
            try:
                found = src.discover_models()
                for m in found:
                    if not is_in_tracking_scope(m):
                        continue
                    canon_key = re.sub(r"[^a-z0-9]", "", m.canonical_id.lower())
                    if not canon_key:
                        continue

                    if canon_key not in all_models:
                        all_models[canon_key] = m
                    else:
                        existing = all_models[canon_key]
                        # Prefer CONFIRMED/TRUSTED release provenance
                        if existing.release_evidence_level not in (ReleaseEvidenceLevel.CONFIRMED.value, ReleaseEvidenceLevel.TRUSTED.value):
                            if m.release_evidence_level in (ReleaseEvidenceLevel.CONFIRMED.value, ReleaseEvidenceLevel.TRUSTED.value):
                                existing.release_date = m.release_date
                                existing.release_evidence_level = m.release_evidence_level
                                existing.release_confirmed = m.release_confirmed
                        if not existing.input_price_per_m and m.input_price_per_m:
                            existing.input_price_per_m = m.input_price_per_m
                        if not existing.output_price_per_m and m.output_price_per_m:
                            existing.output_price_per_m = m.output_price_per_m
                        if not existing.output_tokens_per_sec and m.output_tokens_per_sec:
                            existing.output_tokens_per_sec = m.output_tokens_per_sec
                        existing.headline_indices.update(m.headline_indices)
            except Exception as e:
                logger.warning(f"Error discovering models from {src.name}: {e}")

        for m in all_models.values():
            confirm_release_fallback(m)

        return list(all_models.values())

    def resolve_model(self, model_query: str, candidates: Optional[List[ModelMetadata]] = None) -> ModelMetadata:
        """Resolves user-supplied model query to canonical ModelMetadata from structured benchmarks.

        Raises:
            ModelNotFoundError: If no candidate matches query.
            AmbiguousModelError: If multiple distinct models match query.
        """
        if candidates is None:
            candidates = self.discover_all_candidates()

        q_clean = re.sub(r"[^a-z0-9]", "", model_query.lower())
        if not q_clean:
            raise ModelNotFoundError(f"Invalid empty model identifier: '{model_query}'")

        # 1. Exact match on canonical_id or display_name
        for m in candidates:
            m_canon = re.sub(r"[^a-z0-9]", "", m.canonical_id.lower())
            m_disp = re.sub(r"[^a-z0-9]", "", m.display_name.lower())
            if q_clean == m_canon or q_clean == m_disp:
                return m

        # 2. Substring matching
        matches = []
        for m in candidates:
            m_canon = re.sub(r"[^a-z0-9]", "", m.canonical_id.lower())
            m_disp = re.sub(r"[^a-z0-9]", "", m.display_name.lower())
            if q_clean in m_canon or q_clean in m_disp:
                matches.append(m)

        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            exact_prefix_matches = [
                m for m in matches
                if m.canonical_id.lower().startswith(model_query.lower())
                or m.display_name.lower().startswith(model_query.lower())
            ]
            if len(exact_prefix_matches) == 1:
                return exact_prefix_matches[0]

            matched_ids = [m.canonical_id for m in matches[:6]]
            raise AmbiguousModelError(
                f"Ambiguous model identifier '{model_query}'. Multiple matches found: {matched_ids}. "
                "Please specify a more exact model name."
            )

        raise ModelNotFoundError(
            f"Model '{model_query}' could not be resolved in any structured benchmark source "
            "(LiveBench, SWE-bench, Harbor Hub, Artificial Analysis)."
        )

    def get_pending_models(
        self,
        state: WatcherState,
        force_model: Optional[str] = None,
        is_bootstrap: bool = False,
    ) -> List[ModelMetadata]:
        candidates = self.discover_all_candidates()

        if is_bootstrap:
            for m in candidates:
                state.record_seen(
                    canonical_id=m.canonical_id,
                    display_name=m.display_name,
                    provider=m.provider,
                    release_date=m.release_date,
                    release_evidence_level=m.release_evidence_level,
                    release_confirmed=m.release_confirmed,
                    repository_first_seen=m.repository_first_seen,
                )
            return []

        if force_model:
            matched_model = self.resolve_model(force_model, candidates=candidates)
            return [matched_model]

        pending = []
        for m in candidates:
            if state.should_evaluate(
                canonical_id=m.canonical_id,
                release_date=m.release_date,
                release_evidence_level=m.release_evidence_level,
                release_confirmed=m.release_confirmed,
            ):
                pending.append(m)
            elif m.canonical_id not in state.models:
                # OBSERVED_ONLY or old release: record as SEEN, never alert
                state.record_seen(
                    canonical_id=m.canonical_id,
                    display_name=m.display_name,
                    provider=m.provider,
                    release_date=m.release_date,
                    release_evidence_level=m.release_evidence_level,
                    release_confirmed=m.release_confirmed,
                    repository_first_seen=m.repository_first_seen,
                )

        return pending

    def collect_role_evidence(
        self,
        challenger: str,
        incumbent: str,
        role: Role,
    ) -> List[BenchmarkEvidence]:
        evidence_list: List[BenchmarkEvidence] = []
        for src in self.sources:
            try:
                ev = src.get_evidence(challenger, incumbent, role)
                if ev is not None:
                    evidence_list.append(ev)
            except Exception as e:
                logger.debug(f"Source {src.name} failed to collect evidence for {role}: {e}")

        return evidence_list
