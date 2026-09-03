"""Comparative evaluation engine matching challenger against incumbent across 7 roles."""
from typing import Dict, List, Optional, Tuple
import logging

from model_watcher.config import UserProfile
from model_watcher.types import (
    BenchmarkEvidence,
    CapabilityVerdict,
    EvaluationReport,
    ModelMetadata,
    ReplaceVerdict,
    Role,
    RoleEvaluation,
)

logger = logging.getLogger(__name__)


class ModelEvaluator:
    def __init__(self, profile: UserProfile):
        self.profile = profile

    def evaluate_role(
        self,
        role: Role,
        challenger: ModelMetadata,
        evidence_list: List[BenchmarkEvidence],
    ) -> RoleEvaluation:
        incumbent_name = self.profile.get_incumbent(role)
        challenger_name = challenger.display_name

        # Reviewer Golden Rule: Must output '? Insufficient evidence' if no direct code-review evidence
        if role == Role.REVIEWER:
            direct_review_ev = [
                e for e in evidence_list
                if "review" in e.benchmark.lower() or "critic" in e.benchmark.lower() or "bug" in e.benchmark.lower()
            ]
            if not direct_review_ev:
                return RoleEvaluation(
                    role=role,
                    incumbent_model=incumbent_name,
                    challenger_model=challenger_name,
                    capability=CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                    replace=ReplaceVerdict.NO,
                    replace_rationale="No direct code-review or adversarial bug-finding benchmark evidence. Reviewer requires strict direct evidence; retaining incumbent.",
                    primary_evidence=None,
                    all_evidence=[],
                )

        if not evidence_list:
            return RoleEvaluation(
                role=role,
                incumbent_model=incumbent_name,
                challenger_model=challenger_name,
                capability=CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                replace=ReplaceVerdict.NO,
                replace_rationale="No verifiable comparative benchmark evidence available for this role; retaining incumbent.",
                primary_evidence=None,
                all_evidence=[],
            )

        # Pick primary evidence (prefer highest confidence)
        primary_ev = sorted(evidence_list, key=lambda e: e.confidence, reverse=True)[0]

        # Calculate capability verdict
        c_score = primary_ev.score_challenger
        i_score = primary_ev.score_incumbent

        if c_score is None:
            capability = CapabilityVerdict.INSUFFICIENT_EVIDENCE
            replace = ReplaceVerdict.NO
            rationale = "Benchmark score unavailable for challenger; retaining incumbent."
        elif i_score is None:
            # Only challenger score is known
            if c_score >= 80.0:
                capability = CapabilityVerdict.PROBABLY_BETTER
                replace = ReplaceVerdict.NO
                rationale = f"Challenger achieved strong score ({c_score}{primary_ev.display_metric}), but incumbent baseline score is unverified on same benchmark."
            else:
                capability = CapabilityVerdict.NO_ADVANTAGE
                replace = ReplaceVerdict.NO
                rationale = "Challenger score is moderate without direct incumbent head-to-head comparison."
        else:
            delta = c_score - i_score
            # Relative thresholding
            if delta >= 5.0:
                capability = CapabilityVerdict.CLEARLY_BETTER
            elif 1.5 <= delta < 5.0:
                capability = CapabilityVerdict.PROBABLY_BETTER
            elif -1.5 <= delta < 1.5:
                capability = CapabilityVerdict.NO_ADVANTAGE
            else:
                capability = CapabilityVerdict.PROBABLY_WORSE

            # Replacement analysis (Capability != Replacement)
            replace, rationale = self._determine_replacement(
                role=role,
                capability=capability,
                delta=delta,
                challenger=challenger,
                primary_ev=primary_ev,
                incumbent_name=incumbent_name,
            )

        return RoleEvaluation(
            role=role,
            incumbent_model=incumbent_name,
            challenger_model=challenger_name,
            capability=capability,
            replace=replace,
            replace_rationale=rationale,
            primary_evidence=primary_ev,
            all_evidence=evidence_list,
        )

    def _determine_replacement(
        self,
        role: Role,
        capability: CapabilityVerdict,
        delta: float,
        challenger: ModelMetadata,
        primary_ev: BenchmarkEvidence,
        incumbent_name: str,
    ) -> Tuple[ReplaceVerdict, str]:
        # 1. If worse or no advantage, never replace primary
        if capability in (CapabilityVerdict.PROBABLY_WORSE, CapabilityVerdict.NO_ADVANTAGE, CapabilityVerdict.INSUFFICIENT_EVIDENCE):
            return ReplaceVerdict.NO, f"Challenger shows no meaningful capability edge over {incumbent_name} (delta: {delta:+.1f}{primary_ev.display_metric})."

        # 2. If only marginal advantage (1.5 <= delta < 5.0), default NO
        if capability == CapabilityVerdict.PROBABLY_BETTER:
            if primary_ev.known_uncertainty and "harness" in primary_ev.known_uncertainty.lower():
                return ReplaceVerdict.NO, f"Advantage of +{delta:.1f}{primary_ev.display_metric} may be artifact of test harness ({primary_ev.known_uncertainty}). Not worth switching risk."
            return ReplaceVerdict.NO, f"Marginal lead (+{delta:.1f}{primary_ev.display_metric}) is insufficient to justify migration and switching overhead."

        # 3. If clearly better (delta >= 5.0)
        if capability == CapabilityVerdict.CLEARLY_BETTER:
            # Check harness comparability
            if primary_ev.known_uncertainty and "harness" in primary_ev.known_uncertainty.lower():
                return ReplaceVerdict.NO, f"Substantial lead (+{delta:.1f}{primary_ev.display_metric}) observed, but harness incompatibility detected ({primary_ev.known_uncertainty}). Await verified apples-to-apples run before replacing {incumbent_name}."

            # Check accessibility constraint
            accessible = self.profile.is_accessible(challenger.canonical_id) or self.profile.is_accessible(challenger.display_name)
            if not accessible:
                return ReplaceVerdict.NO, f"Model exhibits superior performance (+{delta:.1f}{primary_ev.display_metric}), but is not currently accessible in user subscription profile."

            return ReplaceVerdict.YES, f"Clear and verified capability advantage (+{delta:.1f}{primary_ev.display_metric} on {primary_ev.benchmark}) justifies route migration."

        return ReplaceVerdict.NO, "Default conservative retention of established incumbent."

    def build_report(
        self,
        challenger: ModelMetadata,
        role_evaluations: Dict[Role, RoleEvaluation],
    ) -> EvaluationReport:
        routes_changed = sum(1 for ev in role_evaluations.values() if ev.replace == ReplaceVerdict.YES)
        total_routes = len(Role)

        # Determine overall verdict
        if routes_changed >= 3:
            overall_verdict = "建议加入"
        elif routes_changed in (1, 2):
            overall_verdict = "部分替换"
        else:
            any_clearly_better = any(ev.capability == CapabilityVerdict.CLEARLY_BETTER for ev in role_evaluations.values())
            is_substantially_cheaper = (
                challenger.input_price_per_m is not None and challenger.input_price_per_m < 1.0
            )
            if any_clearly_better or is_substantially_cheaper:
                overall_verdict = "值得关注"
            else:
                overall_verdict = "可以忽略"

        suggested_adjustments = []
        kept_incumbents = []
        new_use_cases = []
        evidence_ledger: List[BenchmarkEvidence] = []

        for role, ev in role_evaluations.items():
            if ev.primary_evidence:
                evidence_ledger.append(ev.primary_evidence)

            if ev.replace == ReplaceVerdict.YES:
                suggested_adjustments.append(f"{role.display_name}: {ev.incumbent_model} → {ev.challenger_model}")
            else:
                kept_incumbents.append(f"{role.display_name}: Retain {ev.incumbent_model} ({ev.replace_rationale})")

        # Check for new specialist / worker use cases
        if challenger.input_price_per_m is not None and challenger.input_price_per_m <= 0.8:
            new_use_cases.append(f"Cheap background worker / subagent (${challenger.input_price_per_m}/1M input tokens)")
        if role_evaluations.get(Role.CODER) and role_evaluations[Role.CODER].capability in (CapabilityVerdict.CLEARLY_BETTER, CapabilityVerdict.PROBABLY_BETTER):
            new_use_cases.append("Specialist builder for high-difficulty coding issues")
        if role_evaluations.get(Role.MULTIMODAL) and role_evaluations[Role.MULTIMODAL].capability in (CapabilityVerdict.CLEARLY_BETTER, CapabilityVerdict.PROBABLY_BETTER):
            new_use_cases.append("Multimodal document & chart analysis specialist")

        # Key takeaway
        if routes_changed > 0:
            key_takeaway = f"Upgrades {routes_changed}/{total_routes} active roles, led by {suggested_adjustments[0]}."
        elif overall_verdict == "值得关注":
            key_takeaway = "Shows frontier capabilities or attractive pricing, but lacks sufficient verified margin to replace active primary routes."
        else:
            key_takeaway = "Finished evaluation: no dimension sufficiently alters current model routing; safe to ignore this release."

        return EvaluationReport(
            model=challenger,
            overall_verdict=overall_verdict,
            routes_changed=routes_changed,
            total_routes=total_routes,
            role_evaluations=role_evaluations,
            suggested_adjustments=suggested_adjustments,
            kept_incumbents=kept_incumbents,
            new_use_cases=new_use_cases,
            key_takeaway=key_takeaway,
            evidence_ledger=evidence_ledger,
            baseline_revision=self.profile.revision,
            baseline_calibrated_at=self.profile.calibrated_at,
        )
