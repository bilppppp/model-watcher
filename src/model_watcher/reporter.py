"""Markdown 30-second actionable report formatter."""
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Dict

from model_watcher.types import (
    CapabilityVerdict,
    EvaluationReport,
    ReleaseEvidenceLevel,
    ReplaceVerdict,
    Role,
)

CAPABILITY_CN_MAP = {
    CapabilityVerdict.CLEARLY_BETTER: "↑ 明显更强",
    CapabilityVerdict.PROBABLY_BETTER: "↗ 大概率更强",
    CapabilityVerdict.NO_ADVANTAGE: "= 无显著优势",
    CapabilityVerdict.PROBABLY_WORSE: "↘ 大概率更弱",
    CapabilityVerdict.INSUFFICIENT_EVIDENCE: "? 证据不足",
}

REPLACE_CN_MAP = {
    ReplaceVerdict.YES: "是",
    ReplaceVerdict.NO: "否",
}


def get_capability_cn(cap) -> str:
    if isinstance(cap, CapabilityVerdict):
        return CAPABILITY_CN_MAP.get(cap, cap.value)
    for k, v in CAPABILITY_CN_MAP.items():
        if k.value == cap or v == cap:
            return v
    return str(cap)


def get_replace_cn(rep) -> str:
    if isinstance(rep, ReplaceVerdict):
        return REPLACE_CN_MAP.get(rep, rep.value)
    if rep in ("Yes", "yes", True):
        return "是"
    if rep in ("No", "no", False):
        return "否"
    return str(rep)


class MarkdownReporter:
    def __init__(self, reports_dir: Path = Path("reports")):
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def format_report(self, report: EvaluationReport) -> str:
        lines = []

        # 1. Headline
        lines.append(f"# 🆕 {report.model.display_name}\n")
        lines.append(f"**结论：** {report.overall_verdict}")
        lines.append(f"**建议调整：** {report.routes_changed} 个角色")
        lines.append(f"**有效评估：** {report.effective_routes_evaluated}/{report.total_routes} 个角色")
        acc_str = "已配置" if getattr(report, "is_accessible", True) else "未配置（未列入当前 Calibration）"
        lines.append(f"**当前可用性：** {acc_str}")

        # Provenance and Calibration lines
        lines.append(f"**当前校准基线：** Revision {report.baseline_revision}（{report.baseline_calibrated_at or 'Initial'}）")
        if report.model.release_evidence_level == ReleaseEvidenceLevel.INFERRED.value:
            lines.append(f"**发布日期：** {report.model.release_date or '未知'} *(INFERRED: 推断自厂商标准模型版本标识，非官方直接确证)*")
        elif report.model.release_evidence_level in (ReleaseEvidenceLevel.CONFIRMED.value, ReleaseEvidenceLevel.TRUSTED.value):
            lines.append(f"**发布日期：** {report.model.release_date} *({report.model.release_evidence_level}: 官方或高可信来源确证)*")
        elif report.model.repository_first_seen:
            lines.append(f"**Hub 仓库时间：** {report.model.repository_first_seen} *(OBSERVED_ONLY: 仓库创建时间，非官方正式发布日期)*")

        lines.append("")

        # 0/7 routes disclaimer
        if report.routes_changed == 0:
            if report.overall_verdict == "值得关注":
                lines.append("> 暂不调整当前路由，但存在值得继续观察的能力或价格信号。\n")
            else:
                lines.append("> 没有发现足以改变当前工作流的信号，可以忽略本次发布。\n")

        # 2. Main Comparison Table (Prioritize evaluated roles)
        evaluated_roles = [
            (role, report.role_evaluations[role])
            for role in Role
            if role in report.role_evaluations and report.role_evaluations[role].capability != CapabilityVerdict.INSUFFICIENT_EVIDENCE
        ]

        if evaluated_roles:
            lines.append("| 角色 | 当前模型 | 能力判断 | 建议 |")
            lines.append("|---|---|---|---|")
            for role, reval in evaluated_roles:
                cap_val = get_capability_cn(reval.capability)
                if reval.replace == ReplaceVerdict.YES:
                    rec_str = "建议替换"
                elif reval.capability in (CapabilityVerdict.CLEARLY_BETTER, CapabilityVerdict.PROBABLY_BETTER):
                    rec_str = "暂不切换，继续观察"
                else:
                    rec_str = "保留"
                inc_val = reval.incumbent_model
                lines.append(f"| {role.display_name} | {inc_val} | {cap_val} | {rec_str} |")
            lines.append("")

        # 3. Suggested Adjustments
        lines.append("## 建议调整\n")
        if report.suggested_adjustments:
            for adj in report.suggested_adjustments:
                lines.append(f"- {adj}")
            if not report.is_accessible:
                price_info = ""
                if report.model.input_price_per_m is not None and report.model.output_price_per_m is not None:
                    price_info = f"（参考价格：输入 ${report.model.input_price_per_m}/1M tokens，输出 ${report.model.output_price_per_m}/1M tokens）"
                elif report.model.input_price_per_m is not None:
                    price_info = f"（参考价格：输入 ${report.model.input_price_per_m}/1M tokens）"
                lines.append(f"\n> 💡 该模型尚未列入当前 Calibration 的可用模型，若需要新增订阅/API，请结合价格{price_info}决定是否获取。")
        else:
            lines.append("暂无足够证据支持调整当前路由。")
        lines.append("")

        # 4. Kept Incumbents (Only evaluated kept roles)
        lines.append("## 保持不动\n")
        if report.kept_incumbents:
            for k in report.kept_incumbents:
                lines.append(f"- {k}")
        else:
            if report.routes_changed > 0:
                lines.append("- 本次有效评估的角色均建议调整。")
            else:
                lines.append("- 暂无明确保留的有效评估角色。")
        lines.append("")

        # 5. Unevaluated Roles (Insufficient Evidence)
        unevaluated_roles = [
            (role, report.role_evaluations.get(role))
            for role in Role
            if role not in report.role_evaluations or report.role_evaluations[role].capability == CapabilityVerdict.INSUFFICIENT_EVIDENCE
        ]
        if unevaluated_roles:
            lines.append("## 暂未判断\n")
            role_names = "、".join([r.display_name for r, _ in unevaluated_roles])
            lines.append(f"{role_names}目前缺少可靠的直接可比数据，本次不据此做路由判断。\n")
            for role, reval in unevaluated_roles:
                inc_str = f"（当前模型：{reval.incumbent_model}）" if reval and reval.incumbent_model else ""
                reason = "缺少直接的代码审查与缺陷挖掘评测证据（遵循 Reviewer 严格准则，不以纯编码或推理指标替代）" if role == Role.REVIEWER else (
                    "缺少可靠的长程架构规划与复杂任务编排基准证据" if role == Role.PLANNER else (
                        "缺少同环境下的标准化直接可比多模态基准证据" if role == Role.MULTIMODAL else "缺少可靠的直接可比基准证据"
                    )
                )
                lines.append(f"- **{role.display_name}**{inc_str}：{reason}")
            lines.append("")

        # 6. New Use Cases
        lines.append("## 新用途\n")
        if report.new_use_cases:
            for u in report.new_use_cases:
                lines.append(f"- {u}")
        else:
            lines.append("- 暂无额外专有角色建议。")
        lines.append("")

        # 7. Key Takeaway
        lines.append("## 最值得知道的一点\n")
        lines.append(report.key_takeaway or "本次发布对当前模型工作流分工无实质性影响。")
        lines.append("")

        # 8. Evidence / Confidence
        lines.append("## 证据 / 置信度\n")
        if report.evidence_ledger:
            for ev in report.evidence_ledger:
                lines.append(f"- **来源：** {ev.source} | **基准：** {ev.benchmark} ({ev.version})")
                challenger_score_str = f"{ev.score_challenger}{ev.display_metric}" if ev.score_challenger is not None else "N/A"
                if ev.score_incumbent is not None:
                    incumbent_score_str = f" vs 当前模型: {ev.score_incumbent}{ev.display_metric}"
                else:
                    incumbent_score_str = ""
                lines.append(f"  - **得分：** 候选模型: {challenger_score_str}{incumbent_score_str}")
                lines.append(f"  - **评测环境：** {ev.harness}")
                lines.append(f"  - **URL：** {ev.url}")
                lines.append(f"  - **置信度：** {int(ev.confidence * 100)}%")
                if ev.known_uncertainty:
                    lines.append(f"  - **不确定性：** {ev.known_uncertainty}")
                lines.append("")
        else:
            lines.append("- 缺乏独立公开的标准化基准测试分数；暂无高置信度核心证据。\n")

        return "\n".join(lines)

    def save_report(self, report: EvaluationReport) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        safe_model_id = report.model.canonical_id.replace("/", "_").replace(":", "_")
        filename = f"{date_str}_{safe_model_id}.md"
        out_path = self.reports_dir / filename

        content = self.format_report(report)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

        return out_path

    def format_multi_compare_summary(
        self,
        reports: list,
    ) -> str:
        """Generates a cross-model summary table:
        | 角色 | 当前模型 | Model A | Model B | Model C | 建议 |
        """
        lines = []
        lines.append("# 📊 多模型比较总结\n")
        if reports:
            first = reports[0]
            lines.append(f"**当前校准基线：** Revision {first.baseline_revision}（{first.baseline_calibrated_at or 'Initial'}）\n")

        model_headers = [r.model.display_name for r in reports]
        header_row = "| 角色 | 当前模型 | " + " | ".join(model_headers) + " | 建议 |"
        sep_row = "|---|---|" + "|".join(["---"] * len(reports)) + "|---|"
        lines.append(header_row)
        lines.append(sep_row)

        for role in Role:
            current_incumbent = reports[0].role_evaluations[role].incumbent_model if reports and role in reports[0].role_evaluations else "Current"
            row_items = [role.display_name, current_incumbent]

            for r in reports:
                ev = r.role_evaluations.get(role)
                if ev:
                    row_items.append(get_capability_cn(ev.capability))
                else:
                    row_items.append(CAPABILITY_CN_MAP[CapabilityVerdict.INSUFFICIENT_EVIDENCE])

            rec = self.resolve_role_cross_recommendation(role, current_incumbent, reports)
            row_items.append(rec)
            lines.append("| " + " | ".join(row_items) + " |")

        lines.append("")
        return "\n".join(lines)

    def resolve_role_cross_recommendation(
        self,
        role: Role,
        current_incumbent: str,
        reports: list,
    ) -> str:
        """Computes order-invariant cross-model recommendation for a given role across challenger reports.

        Rules:
        1. Identifies challengers that warrant replacement (replace == ReplaceVerdict.YES).
        2. If 0 replace challengers:
           - If any candidate is CLEARLY_BETTER or PROBABLY_BETTER: 保留 {current_incumbent}（微弱领先不建议切换）.
           - Otherwise: 保留 {current_incumbent}.
        3. If exactly 1 replace challenger:
           - Recommend that challenger: **{challenger}**（建议替换）.
        4. If multiple replace challengers:
           - Find common benchmark evidence across ALL of them with:
             - same source, benchmark name, version, metric
             - comparable/identical harness without harness discrepancy uncertainties
             - challenger score present
           - If directly comparable common benchmark evidence exists:
             - Sort candidates deterministically by score descending, then display_name ascending.
             - If clear top score: **{top_model}**（在 {benchmark} 上取得最高分 {top_score:.1f}{metric}）
             - If tie: 并列：{Model A} / {Model B}（在 {benchmark} 上同得 {score:.1f}{metric}）
           - If no directly comparable common benchmark evidence exists across all replace challengers:
             - Output: "{Model A} / {Model B} 均优于当前模型；但缺乏足够的直接可比证据，无法可靠排序。"
        5. Completely order-invariant: compare A B C and compare C B A yield identical conclusions.
        """
        from model_watcher.types import CapabilityVerdict, ReplaceVerdict

        replace_yes_reports = [
            r for r in reports
            if r.role_evaluations.get(role) and r.role_evaluations[role].replace == ReplaceVerdict.YES
        ]

        if not replace_yes_reports:
            better_candidates = [
                r for r in reports
                if r.role_evaluations.get(role)
                and r.role_evaluations[role].capability in (CapabilityVerdict.CLEARLY_BETTER, CapabilityVerdict.PROBABLY_BETTER)
            ]
            if better_candidates:
                return f"保留 {current_incumbent}（微弱领先不建议切换）"
            return f"保留 {current_incumbent}"

        if len(replace_yes_reports) == 1:
            return f"**{replace_yes_reports[0].model.display_name}**（建议替换）"

        # Multiple replace challengers: find common comparable benchmarks
        candidate_ev_maps = {}
        all_benchmark_keys = None

        for r in replace_yes_reports:
            c_map = {}
            r_eval = r.role_evaluations[role]
            ev_list = list(r_eval.all_evidence)
            if r_eval.primary_evidence and r_eval.primary_evidence not in ev_list:
                ev_list.append(r_eval.primary_evidence)

            for ev in ev_list:
                if ev.score_challenger is not None:
                    b_key = (ev.source, ev.benchmark, ev.version, ev.display_metric)
                    c_map[b_key] = (float(ev.score_challenger), ev.harness, ev.known_uncertainty)

            candidate_ev_maps[r.model.display_name] = c_map
            if all_benchmark_keys is None:
                all_benchmark_keys = set(c_map.keys())
            else:
                all_benchmark_keys &= set(c_map.keys())

        valid_common_keys = []
        if all_benchmark_keys:
            for b_key in sorted(all_benchmark_keys):
                harnesses = set(candidate_ev_maps[r.model.display_name][b_key][1] for r in replace_yes_reports)
                uncertainties = [candidate_ev_maps[r.model.display_name][b_key][2] for r in replace_yes_reports]
                has_harness_issue = any(
                    ("harness difference" in (u or "").lower() or "incompatib" in (u or "").lower() or "different harness" in (u or "").lower())
                    and "composite" not in (u or "").lower()
                    for u in uncertainties
                )
                if len(harnesses) == 1 and not has_harness_issue:
                    valid_common_keys.append(b_key)

        if valid_common_keys:
            chosen_key = valid_common_keys[0]
            source, benchmark, version, metric = chosen_key

            scores_list = []
            for r in replace_yes_reports:
                name = r.model.display_name
                score = candidate_ev_maps[name][chosen_key][0]
                scores_list.append((score, name))

            scores_list.sort(key=lambda item: (-item[0], item[1]))

            top_score, top_name = scores_list[0]
            tied = [name for score, name in scores_list if abs(score - top_score) < 1e-6]

            metric_str = metric if metric else ""
            if len(tied) > 1:
                tied.sort()
                return f"并列：{' / '.join(tied)}（在 {benchmark} 上同得 {top_score:.1f}{metric_str}）"
            else:
                return f"**{top_name}**（在 {benchmark} 上取得最高分 {top_score:.1f}{metric_str}）"

        # No common benchmark among Replace: Yes candidates
        names_sorted = sorted([r.model.display_name for r in replace_yes_reports])
        return f"{' / '.join(names_sorted)} 均优于当前模型；但缺乏足够的直接可比证据，无法可靠排序。"

    def save_comparison_report(self, content: str, tag: str = "comparison") -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        safe_tag = tag.replace("/", "_").replace(":", "_").replace(" ", "_")
        filename = f"{date_str}_{safe_tag}.md"
        out_path = self.reports_dir / filename
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        return out_path
