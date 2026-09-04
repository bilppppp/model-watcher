"""Core domain types for Model Watcher."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Role(str, Enum):
    CODER = "coder"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    REASONER = "reasoner"
    ANALYST = "analyst"
    AGENT = "agent"
    MULTIMODAL = "multimodal"

    @property
    def display_name(self) -> str:
        names = {
            Role.CODER: "编码 / 构建",
            Role.PLANNER: "规划",
            Role.REVIEWER: "审查",
            Role.REASONER: "推理",
            Role.ANALYST: "分析 / 研究",
            Role.AGENT: "Agent / 工具执行",
            Role.MULTIMODAL: "多模态",
        }
        return names[self]


class CapabilityVerdict(str, Enum):
    CLEARLY_BETTER = "↑ Clearly better"
    PROBABLY_BETTER = "↗ Probably better"
    NO_ADVANTAGE = "= No meaningful advantage"
    PROBABLY_WORSE = "↘ Probably worse"
    INSUFFICIENT_EVIDENCE = "? Insufficient evidence"


class ReplaceVerdict(str, Enum):
    YES = "Yes"
    NO = "No"


class ModelLifecycleStatus(str, Enum):
    SEEN = "SEEN"                    # Historical baseline or unconfirmed entry; not newly released
    PROVISIONAL = "PROVISIONAL"      # Newly released challenger; initial provisional evaluation completed
    MATURE = "MATURE"                # Re-evaluated ~7 days later or established incumbent


class ReleaseEvidenceLevel(str, Enum):
    CONFIRMED = "CONFIRMED"          # Vendor official release page / changelog / model card explicit release date
    TRUSTED = "TRUSTED"              # Artificial Analysis verified release_date
    INFERRED = "INFERRED"            # Trusted provider's canonical model ID contains explicit legal version date
    OBSERVED_ONLY = "OBSERVED_ONLY"  # HF repo createdAt, benchmark submission date, GitHub commit date


@dataclass
class BenchmarkEvidence:
    source: str
    benchmark: str
    version: str
    score_challenger: Optional[float] = None
    score_incumbent: Optional[float] = None
    display_metric: str = "%"
    harness: str = "standard"
    url: str = ""
    confidence: float = 0.8
    known_uncertainty: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "benchmark": self.benchmark,
            "version": self.version,
            "score_challenger": self.score_challenger,
            "score_incumbent": self.score_incumbent,
            "display_metric": self.display_metric,
            "harness": self.harness,
            "url": self.url,
            "confidence": self.confidence,
            "known_uncertainty": self.known_uncertainty,
        }


@dataclass
class RoleEvaluation:
    role: Role
    incumbent_model: str
    challenger_model: str
    capability: CapabilityVerdict
    replace: ReplaceVerdict
    replace_rationale: str
    primary_evidence: Optional[BenchmarkEvidence] = None
    all_evidence: List[BenchmarkEvidence] = field(default_factory=list)
    is_accessible: bool = True


@dataclass
class ModelMetadata:
    canonical_id: str
    display_name: str
    provider: str
    release_date: Optional[str] = None
    release_evidence_level: str = ReleaseEvidenceLevel.OBSERVED_ONLY.value
    release_confirmed: bool = False
    repository_first_seen: Optional[str] = None
    benchmark_first_seen: str = ""
    input_price_per_m: Optional[float] = None
    output_price_per_m: Optional[float] = None
    output_tokens_per_sec: Optional[float] = None
    time_to_first_token_sec: Optional[float] = None
    headline_indices: Dict[str, Optional[float]] = field(default_factory=dict)
    first_seen: str = ""
    raw_source: str = ""


@dataclass
class EvaluationReport:
    model: ModelMetadata
    overall_verdict: str  # "值得关注" | "建议加入" | "部分替换" | "可以忽略"
    routes_changed: int
    total_routes: int = 7
    role_evaluations: Dict[Role, RoleEvaluation] = field(default_factory=dict)
    suggested_adjustments: List[str] = field(default_factory=list)
    kept_incumbents: List[str] = field(default_factory=list)
    new_use_cases: List[str] = field(default_factory=list)
    key_takeaway: str = ""
    evidence_ledger: List[BenchmarkEvidence] = field(default_factory=list)
    created_at: str = ""
    baseline_revision: int = 1
    baseline_calibrated_at: str = ""
    is_accessible: bool = True

    @property
    def effective_routes_evaluated(self) -> int:
        return sum(
            1 for ev in self.role_evaluations.values()
            if ev.capability != CapabilityVerdict.INSUFFICIENT_EVIDENCE
        )

    @property
    def unevaluated_roles(self) -> List[RoleEvaluation]:
        return [
            ev for ev in self.role_evaluations.values()
            if ev.capability == CapabilityVerdict.INSUFFICIENT_EVIDENCE
        ]


class ModelNotFoundError(Exception):
    """Raised when a specified model cannot be resolved in any structured source."""
    pass


class AmbiguousModelError(Exception):
    """Raised when a model identifier matches multiple candidates."""
    pass


class NeedsCalibrationError(Exception):
    """Raised when operation requires baseline calibration but none exists."""
    pass
