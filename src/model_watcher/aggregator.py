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
from model_watcher.types import BenchmarkEvidence, ModelMetadata, ReleaseEvidenceLevel, Role

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


def query_huggingface_repository_created_at(model_id: str) -> Optional[str]:
    """Queries official Hugging Face Hub for repo creation date.

    Note per Hugging Face documentation:
    'createdAt' reflects repository creation on Hub, NOT official model release date.
    Saved strictly as repository_first_seen (OBSERVED_ONLY).
    """
    clean_id = re.sub(r"-(high|medium|low|xhigh|thinking|preview|instruct|fp8|chat)$", "", model_id.lower())
    search_term = clean_id.split("-")[0] if "-" in clean_id else clean_id
    if len(search_term) < 3:
        search_term = clean_id

    url = f"https://huggingface.co/api/models?search={urllib.parse.quote(search_term)}&limit=3"
    req = urllib.request.Request(url, headers={"User-Agent": "ModelWatcher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for item in data:
                item_id = item.get("id", "").lower()
                created_at = item.get("createdAt")
                if created_at and (clean_id in item_id or item_id in clean_id):
                    return created_at[:10]
    except Exception as e:
        logger.debug(f"HF model query skipped for {model_id}: {e}")
    return None


def confirm_release_fallback(model: ModelMetadata) -> None:
    """Classifies release evidence level: CONFIRMED, TRUSTED, INFERRED, or OBSERVED_ONLY.

    - CONFIRMED / TRUSTED: already confirmed by official source or AA
    - INFERRED: trusted provider canonical model identifier contains explicit date
    - OBSERVED_ONLY: HF repo createdAt, benchmark submission date
    """
    # 1. Query HF repo createdAt as repository_first_seen (OBSERVED_ONLY evidence)
    if not model.repository_first_seen:
        hf_created = query_huggingface_repository_created_at(model.canonical_id)
        if hf_created:
            model.repository_first_seen = hf_created

    # If already confirmed or trusted, keep existing high-confidence provenance
    if model.release_evidence_level in (ReleaseEvidenceLevel.CONFIRMED.value, ReleaseEvidenceLevel.TRUSTED.value):
        return

    # 2. Check if trusted provider's canonical model ID explicitly includes version date
    if is_trusted_provider(model.provider, model.canonical_id):
        date_in_name = extract_date_from_name(model.canonical_id) or extract_date_from_name(model.display_name)
        if date_in_name:
            model.release_date = date_in_name
            model.release_evidence_level = ReleaseEvidenceLevel.INFERRED.value
            model.release_confirmed = False  # Inferred, not confirmed
            return

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
            norm_target = re.sub(r"[^a-z0-9]", "", force_model.lower())
            matched = [
                m for m in candidates
                if norm_target in re.sub(r"[^a-z0-9]", "", m.canonical_id.lower())
                or norm_target in re.sub(r"[^a-z0-9]", "", m.display_name.lower())
            ]
            if matched:
                return matched[:1]
            return [
                ModelMetadata(
                    canonical_id=force_model,
                    display_name=force_model,
                    provider="Targeted Model",
                    first_seen="2026-09-03",
                    release_confirmed=True,
                    release_evidence_level=ReleaseEvidenceLevel.CONFIRMED.value,
                    raw_source="Targeted Evaluation",
                )
            ]

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
