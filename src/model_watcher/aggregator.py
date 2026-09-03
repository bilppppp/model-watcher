"""Model discovery and evidence aggregation across structured data sources."""
import datetime
import logging
import re
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
                        # Prefer confirmed release date from trusted discovery source
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

        return list(all_models.values())

    def get_pending_models(
        self,
        state: WatcherState,
        force_model: Optional[str] = None,
        is_bootstrap: bool = False,
    ) -> List[ModelMetadata]:
        """Finds candidate models that qualify for evaluation.

        - If is_bootstrap: records all current candidates into state as baseline SEEN; returns []
        - If force_model: returns specifically targeted model for user-requested evaluation
        - Otherwise: separates 'new benchmark entry' from 'new model release' using release confirmation.
        """
        candidates = self.discover_all_candidates()

        if is_bootstrap:
            # Bootstrap: record all current historical models as SEEN
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
            # Explicit user evaluation request
            norm_target = re.sub(r"[^a-z0-9]", "", force_model.lower())
            matched = [
                m for m in candidates
                if norm_target in re.sub(r"[^a-z0-9]", "", m.canonical_id.lower())
                or norm_target in re.sub(r"[^a-z0-9]", "", m.display_name.lower())
            ]
            if matched:
                return matched[:1]
            # Fallback construct
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
                # Benchmark entry without confirmed recent release date:
                # Record as SEEN to avoid re-checking, but do NOT alert user
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
        """Gathers all available comparative evidence across all data sources."""
        evidence_list: List[BenchmarkEvidence] = []
        for src in self.sources:
            try:
                ev = src.get_evidence(challenger, incumbent, role)
                if ev is not None:
                    evidence_list.append(ev)
            except Exception as e:
                logger.debug(f"Source {src.name} failed to collect evidence for {role}: {e}")

        return evidence_list
