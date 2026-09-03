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
            Role.CODER: "Coder / Builder",
            Role.PLANNER: "Planner",
            Role.REVIEWER: "Reviewer",
            Role.REASONER: "Reasoner",
            Role.ANALYST: "Analyst / Researcher",
            Role.AGENT: "Agent / Computer-use",
            Role.MULTIMODAL: "Multimodal",
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
    NEW = "NEW"
    PROVISIONAL = "PROVISIONAL"
    MATURE = "MATURE"


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


@dataclass
class ModelMetadata:
    canonical_id: str
    display_name: str
    provider: str
    release_date: Optional[str] = None
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
