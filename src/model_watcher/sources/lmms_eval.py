"""LMMs-Eval reference source for multimodal benchmark evaluation."""
import logging
from typing import List, Optional

from model_watcher.sources.base import DataSource
from model_watcher.types import BenchmarkEvidence, ModelMetadata, Role

logger = logging.getLogger(__name__)


class LMMsEvalSource(DataSource):
    """LMMs-Eval framework reference source.

    Note: The LMMs-Eval repository is an evaluation test harness; it does not host an
    auto-updating machine-readable public leaderboard endpoint.
    Per strict audit policy:
    - No static hardcoded score tables are maintained in code.
    - If no live, machine-readable official evaluation results with verified provenance
      are available for a model, Multimodal evaluation strictly returns None,
      resulting in '? Insufficient evidence'.
    """
    name: str = "LMMs-Eval"
    priority: int = 1  # P1

    def discover_models(self) -> List[ModelMetadata]:
        # LMMs-Eval harness does not provide an automated discovery endpoint in repo
        return []

    def get_evidence(
        self,
        challenger: str,
        incumbent: str,
        role: Role,
    ) -> Optional[BenchmarkEvidence]:
        if role != Role.MULTIMODAL:
            return None

        # Without a live, machine-readable official leaderboard endpoint,
        # return None to trigger '? Insufficient evidence'.
        # Do not guess or fabricate scores.
        logger.debug(f"LMMs-Eval: No live machine-readable leaderboard endpoint available for {challenger}.")
        return None
