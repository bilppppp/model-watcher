"""Model discovery and evidence aggregation across structured data sources."""
import datetime
import json
import logging
import re
import urllib.request
from typing import Dict, List, Optional

from model_watcher.sources.artificial_analysis import ArtificialAnalysisSource
from model_watcher.sources.harbor import HarborSource
from model_watcher.sources.livebench import LiveBenchSource
from model_watcher.sources.lmms_eval import LMMsEvalSource
from model_watcher.sources.swebench import SWEBenchSource
from model_watcher.state import WatcherState, is_recent_date
from model_watcher.types import BenchmarkEvidence, ModelMetadata, Role

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


def is_in_tracking_scope(model: ModelMetadata) -> bool:
    """Filter out non-LLM models: embedding, speech-only, image-gen, tiny edge."""
    name_low = model.canonical_id.lower() + " " + model.display_name.lower()
    for pat in OUT_OF_SCOPE_PATTERNS:
        if re.search(pat, name_low):
            return False
    return True


def extract_date_from_name(name: str) -> Optional[str]:
    """Extracts explicit version/release date formatted in model name."""
    # Match YYYY-MM-DD
    m1 = re.search(r"(202[3-9])-([01][0-9])-([0-3][0-9])", name)
    if m1:
        return f"{m1.group(1)}-{m1.group(2)}-{m1.group(3)}"
    # Match YYYYMMDD
    m2 = re.search(r"(202[3-9])([01][0-9])([0-3][0-9])", name)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    return None


def query_huggingface_model_card_date(model_id: str) -> Optional[str]:
    """Fallback query to official Hugging Face Model Card API for open-weights models."""
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
        logger.debug(f"HF model card query skipped for {model_id}: {e}")
    return None


def confirm_release_fallback(model: ModelMetadata) -> None:
    """When AA is unavailable or lacks release date, verify via official name tags or official model cards."""
    if model.release_confirmed and model.release_date:
        return

    # 1. Check embedded version date in model name / ID
    date_in_name = extract_date_from_name(model.canonical_id) or extract_date_from_name(model.display_name)
    if date_in_name:
        model.release_date = date_in_name
        model.release_confirmed = True
        return

    # 2. Check official model card metadata on Hugging Face (for open-weights models)
    hf_date = query_huggingface_model_card_date(model.canonical_id)
    if hf_date:
        model.release_date = hf_date
        model.release_confirmed = True
        return


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
                        if not existing.release_confirmed and m.release_confirmed:
                            existing.release_date = m.release_date
                            existing.release_confirmed = m.release_confirmed
                        elif not existing.release_date and m.release_date:
                            existing.release_date = m.release_date
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

        # Execute fallback release confirmation for candidates lacking AA release date
        for m in all_models.values():
            if not m.release_confirmed:
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
                    release_confirmed=m.release_confirmed,
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
                    raw_source="Targeted Evaluation",
                )
            ]

        pending = []
        for m in candidates:
            if state.should_evaluate(
                canonical_id=m.canonical_id,
                release_date=m.release_date,
                release_confirmed=m.release_confirmed,
            ):
                pending.append(m)
            elif m.canonical_id not in state.models:
                state.record_seen(
                    canonical_id=m.canonical_id,
                    display_name=m.display_name,
                    provider=m.provider,
                    release_date=m.release_date,
                    release_confirmed=m.release_confirmed,
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
