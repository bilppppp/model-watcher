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


def select_primary_evidence(evidence_list: List[BenchmarkEvidence]) -> BenchmarkEvidence:
    """Selects primary evidence with bilateral comparability prioritized over confidence.

    Rules:
    1. Complete bilateral evidence (score_challenger != None and score_incumbent != None) is strictly preferred.
    2. Among complete bilateral evidences, prioritize:
       - Direct comparability (non-composite index > composite index)
       - Harness compatibility (same/compatible harness > conflicting harness)
       - Confidence (higher > lower)
    3. If no complete bilateral evidence exists, pick the highest-quality unilateral evidence
       (preferring presence of challenger score, then higher confidence) to explain Insufficient evidence.
    """
    def _bilateral_sort_key(e: BenchmarkEvidence):
        unc = (e.known_uncertainty or "").lower()
        is_composite = "composite" in unc
        is_harness_diff = (not is_composite) and any(
            k in unc for k in ("harness difference", "harness incompatibility", "different harness", "incompatib")
        )
        is_direct = not is_composite
        harness_compat = not is_harness_diff
        return (
            1 if is_direct else 0,
            1 if harness_compat else 0,
            e.confidence,
        )

    def _unilateral_sort_key(e: BenchmarkEvidence):
        has_challenger = e.score_challenger is not None
        return (
            1 if has_challenger else 0,
            e.confidence,
        )

    complete_bilateral = [
        e for e in evidence_list
        if e.score_challenger is not None and e.score_incumbent is not None
    ]
    if complete_bilateral:
        return sorted(complete_bilateral, key=_bilateral_sort_key, reverse=True)[0]

    return sorted(evidence_list, key=_unilateral_sort_key, reverse=True)[0]


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
        is_acc = self.profile.is_accessible(challenger.canonical_id) or self.profile.is_accessible(challenger.display_name)

        if role == Role.REVIEWER:
            has_review_evidence = any(
                "review" in (e.benchmark or "").lower() or "inspect" in (e.benchmark or "").lower()
                for e in evidence_list
            )
            if not has_review_evidence:
                return RoleEvaluation(
                    role=role,
                    incumbent_model=incumbent_name,
                    challenger_model=challenger_name,
                    capability=CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                    replace=ReplaceVerdict.NO,
                    replace_rationale="审查角色要求严格直接的代码审查与缺陷挖掘证据，暂无直接测试数据，继续保留当前模型。",
                    primary_evidence=None,
                    all_evidence=[],
                    is_accessible=is_acc,
                )

        if not evidence_list:
            return RoleEvaluation(
                role=role,
                incumbent_model=incumbent_name,
                challenger_model=challenger_name,
                capability=CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                replace=ReplaceVerdict.NO,
                replace_rationale="该角色暂无可验证的直接对比基准证据，继续保留当前模型。",
                primary_evidence=None,
                all_evidence=[],
                is_accessible=is_acc,
            )

        # Pick primary evidence (prefer complete bilateral evidence over unilateral high-confidence)
        primary_ev = select_primary_evidence(evidence_list)

        # Calculate capability verdict
        c_score = primary_ev.score_challenger
        i_score = primary_ev.score_incumbent

        if c_score is None:
            capability = CapabilityVerdict.INSUFFICIENT_EVIDENCE
            replace = ReplaceVerdict.NO
            rationale = "候选模型缺少该基准测试得分，继续保留当前模型。"
        elif i_score is None:
            # Missing incumbent comparative score: strictly Insufficient evidence
            capability = CapabilityVerdict.INSUFFICIENT_EVIDENCE
            replace = ReplaceVerdict.NO
            rationale = "当前主力模型在相同基准上缺少直接可比得分，继续保留当前模型。"
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
            is_accessible=is_acc,
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
        accessible = self.profile.is_accessible(challenger.canonical_id) or self.profile.is_accessible(challenger.display_name)
        is_composite = primary_ev.known_uncertainty and "composite" in primary_ev.known_uncertainty.lower()
        is_harness_diff = (
            primary_ev.known_uncertainty
            and not is_composite
            and any(
                k in primary_ev.known_uncertainty.lower()
                for k in ("harness difference", "harness incompatibility", "different harness", "incompatib")
            )
        )

        # 1. If worse or no advantage, never replace primary
        if capability in (CapabilityVerdict.PROBABLY_WORSE, CapabilityVerdict.NO_ADVANTAGE, CapabilityVerdict.INSUFFICIENT_EVIDENCE):
            return ReplaceVerdict.NO, f"候选模型未展现出超越 {incumbent_name} 的明显能力优势（分差：{delta:+.1f}{primary_ev.display_metric}）。"

        # 2. If only marginal advantage (1.5 <= delta < 5.0), default NO
        if capability == CapabilityVerdict.PROBABLY_BETTER:
            if is_composite:
                return (
                    ReplaceVerdict.NO,
                    f"候选模型在综合指数上小幅领先（+{delta:.1f} {primary_ev.display_metric}），缺少直接可比 benchmark 验证，不足以调整当前路由。",
                )
            if is_harness_diff:
                return ReplaceVerdict.NO, f"领先优势（+{delta:.1f}{primary_ev.display_metric}）可能是测试环境（{primary_ev.known_uncertainty}）带来的偏差，不值得冒切换风险。"
            if not accessible:
                return ReplaceVerdict.NO, f"候选模型仅小幅领先（+{delta:.1f}{primary_ev.display_metric}），优势不足以支持为了它新增订阅。"
            return ReplaceVerdict.NO, f"候选模型仅小幅领先（+{delta:.1f}{primary_ev.display_metric}），不足以抵消迁移成本和切换风险。"

        # 3. If clearly better (delta >= 5.0)
        if capability == CapabilityVerdict.CLEARLY_BETTER:
            if is_composite:
                return (
                    ReplaceVerdict.NO,
                    f"观察到明显领先（+{delta:.1f} {primary_ev.display_metric}），但该证据属于跨多个独立评测形成的综合指数，目前缺少直接可比 benchmark 的交叉验证，因此暂不调整路由。",
                )

            # Check harness comparability
            if is_harness_diff:
                return ReplaceVerdict.NO, f"观察到明显领先（+{delta:.1f}{primary_ev.display_metric}），但存在测试环境不兼容（{primary_ev.known_uncertainty}），在获得同环境对比前暂不替换 {incumbent_name}。"

            # accessible_models 不再作为 Replace? 的硬门禁
            if not accessible:
                price_info = ""
                if challenger.input_price_per_m is not None and challenger.output_price_per_m is not None:
                    price_info = f"（参考定价：输入 ${challenger.input_price_per_m}/1M tokens，输出 ${challenger.output_price_per_m}/1M tokens）"
                elif challenger.input_price_per_m is not None:
                    price_info = f"（参考定价：输入 ${challenger.input_price_per_m}/1M tokens）"

                return ReplaceVerdict.YES, f"在 {primary_ev.benchmark} 上具备经确证的明显能力优势（+{delta:.1f}{primary_ev.display_metric}），值得成为该角色首选。该模型尚未列入当前 Calibration 的可用模型，若需要新增订阅/API，请结合价格{price_info}决定是否获取。"

            return ReplaceVerdict.YES, f"在 {primary_ev.benchmark} 上具备经确证的明显能力优势（+{delta:.1f}{primary_ev.display_metric}），建议进行路由迁移。"

        return ReplaceVerdict.NO, "依据谨慎原则，继续保留当前主力模型。"

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
                suggested_adjustments.append(f"{role.display_name}：{ev.incumbent_model} → {ev.challenger_model}")
            else:
                kept_incumbents.append(f"{role.display_name}：保留 {ev.incumbent_model}（{ev.replace_rationale}）")

        # Check for new specialist / worker use cases
        if challenger.input_price_per_m is not None and challenger.input_price_per_m <= 0.8:
            new_use_cases.append(f"极低成本后台执行工 / Subagent（${challenger.input_price_per_m}/1M 输入 Tokens）")

        # Coder specialist requires Clearly Better + direct non-composite benchmark evidence
        coder_eval = role_evaluations.get(Role.CODER)
        if coder_eval and coder_eval.capability == CapabilityVerdict.CLEARLY_BETTER:
            coder_ev = coder_eval.primary_evidence
            is_comp = coder_ev and coder_ev.known_uncertainty and "composite" in coder_ev.known_uncertainty.lower()
            if coder_ev and not is_comp:
                new_use_cases.append("针对高难代码难题的专有构建模型")

        if role_evaluations.get(Role.MULTIMODAL) and role_evaluations[Role.MULTIMODAL].capability in (CapabilityVerdict.CLEARLY_BETTER, CapabilityVerdict.PROBABLY_BETTER):
            new_use_cases.append("多模态文档与图表分析专有模型")

        # Key takeaway
        if routes_changed > 0:
            key_takeaway = f"建议升级 {routes_changed}/{total_routes} 个核心角色路由，以 {suggested_adjustments[0]} 为首。"
        elif overall_verdict == "值得关注":
            key_takeaway = "展现出前沿能力或极具吸引力的定价，但尚缺乏经确证的足够领先优势来替换当前主力。"
        else:
            key_takeaway = "评估完成：没有发现足以改变当前工作流的信号，可以安全忽略本次发布。"

        is_accessible = self.profile.is_accessible(challenger.canonical_id) or self.profile.is_accessible(challenger.display_name)

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
            is_accessible=is_accessible,
        )
