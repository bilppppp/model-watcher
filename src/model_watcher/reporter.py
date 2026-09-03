"""Markdown 30-second actionable report formatter."""
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Dict

from model_watcher.types import (
    CapabilityVerdict,
    EvaluationReport,
    ReleaseEvidenceLevel,
    Role,
)


class MarkdownReporter:
    def __init__(self, reports_dir: Path = Path("reports")):
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def format_report(self, report: EvaluationReport) -> str:
        lines = []

        # 1. Headline
        lines.append(f"# 🆕 {report.model.display_name}\n")
        lines.append(f"**结论：** {report.overall_verdict}")
        lines.append(f"**本次改变：{report.routes_changed}/{report.total_routes} 个当前模型路由**")

        # Provenance and Calibration lines
        lines.append(f"**Baseline Calibration:** Revision {report.baseline_revision} ({report.baseline_calibrated_at or 'Initial'})")
        if report.model.release_evidence_level == ReleaseEvidenceLevel.INFERRED.value:
            lines.append(f"**发布日期：** {report.model.release_date or '未知'} *(INFERRED: 推断自厂商标准模型版本标识，非官方直接确证)*")
        elif report.model.release_evidence_level in (ReleaseEvidenceLevel.CONFIRMED.value, ReleaseEvidenceLevel.TRUSTED.value):
            lines.append(f"**发布日期：** {report.model.release_date} *({report.model.release_evidence_level}: 官方或高可信来源确证)*")
        elif report.model.repository_first_seen:
            lines.append(f"**Hub 仓库时间：** {report.model.repository_first_seen} *(OBSERVED_ONLY: 仓库创建时间，非官方正式发布日期)*")

        lines.append("")

        # 0/7 routes disclaimer
        if report.routes_changed == 0:
            lines.append("> 已完成评估，没有任何维度足以改变当前模型组合，可以忽略这次发布。\n")

        # 2. 7-role Comparison Table
        lines.append("| Role | Current | Challenger | Capability | Replace? |")
        lines.append("|---|---|---|---|---|")
        for role in Role:
            reval = report.role_evaluations.get(role)
            if reval:
                cap_val = reval.capability.value
                rep_val = reval.replace.value
                inc_val = reval.incumbent_model
            else:
                cap_val = CapabilityVerdict.INSUFFICIENT_EVIDENCE.value
                rep_val = "No"
                inc_val = "Unknown"

            lines.append(f"| {role.display_name} | {inc_val} | {report.model.display_name} | {cap_val} | {rep_val} |")
        lines.append("")

        # 3. Suggested Adjustments
        lines.append("## 建议调整\n")
        if report.suggested_adjustments:
            for adj in report.suggested_adjustments:
                lines.append(f"- {adj}")
        else:
            lines.append("无路由调整建议。当前组合保持最优。")
        lines.append("")

        # 4. Kept Incumbents
        lines.append("## 保持不动\n")
        if report.kept_incumbents:
            for k in report.kept_incumbents:
                lines.append(f"- {k}")
        else:
            lines.append("- 全部角色发生调整。")
        lines.append("")

        # 5. New Use Cases
        lines.append("## 新用途\n")
        if report.new_use_cases:
            for u in report.new_use_cases:
                lines.append(f"- {u}")
        else:
            lines.append("- 暂无额外专有角色建议。")
        lines.append("")

        # 6. Key Takeaway
        lines.append("## 最值得知道的一点\n")
        lines.append(report.key_takeaway or "本次发布对当前模型工作流分工无实质性影响。")
        lines.append("")

        # 7. Evidence / Confidence
        lines.append("## Evidence / Confidence\n")
        if report.evidence_ledger:
            for ev in report.evidence_ledger:
                lines.append(f"- **Source:** {ev.source} | **Benchmark:** {ev.benchmark} ({ev.version})")
                challenger_score_str = f"{ev.score_challenger}{ev.display_metric}" if ev.score_challenger is not None else "N/A"
                if ev.score_incumbent is not None:
                    incumbent_score_str = f" vs Incumbent: {ev.score_incumbent}{ev.display_metric}"
                else:
                    incumbent_score_str = ""
                lines.append(f"  - **Score:** Challenger: {challenger_score_str}{incumbent_score_str}")
                lines.append(f"  - **Harness:** {ev.harness}")
                lines.append(f"  - **URL:** {ev.url}")
                lines.append(f"  - **Confidence:** {int(ev.confidence * 100)}%")
                if ev.known_uncertainty:
                    lines.append(f"  - **Uncertainty:** {ev.known_uncertainty}")
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
        | Role | Current | Model A | Model B | Model C | Recommendation |
        """
        lines = []
        lines.append("# 📊 Cross-Model Comparison Summary\n")
        if reports:
            first = reports[0]
            lines.append(f"**Baseline Calibration:** Revision {first.baseline_revision} ({first.baseline_calibrated_at or 'Initial'})\n")

        model_headers = [r.model.display_name for r in reports]
        header_row = "| Role | Current | " + " | ".join(model_headers) + " | Recommendation |"
        sep_row = "|---|---|" + "|".join(["---"] * len(reports)) + "|---|"
        lines.append(header_row)
        lines.append(sep_row)

        for role in Role:
            current_incumbent = reports[0].role_evaluations[role].incumbent_model if reports and role in reports[0].role_evaluations else "Current"
            row_items = [role.display_name, current_incumbent]

            for r in reports:
                ev = r.role_evaluations.get(role)
                if ev:
                    row_items.append(ev.capability.value)
                else:
                    row_items.append("? Insufficient evidence")

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
           - If any candidate is CLEARLY_BETTER or PROBABLY_BETTER: Retain current (Leads not worth switching).
           - Otherwise: Retain current.
        3. If exactly 1 replace challenger:
           - Recommend that challenger: **{challenger}** (Replace: Yes).
        4. If multiple replace challengers:
           - Find common benchmark evidence across ALL of them with:
             - same source, benchmark name, version, metric
             - comparable/identical harness without harness discrepancy uncertainties
             - challenger score present
           - If directly comparable common benchmark evidence exists:
             - Sort candidates deterministically by score descending, then display_name ascending.
             - If clear top score: **{top_model}** ({top_score:.1f}{metric} on {benchmark})
             - If tie: Tie: {Model A} / {Model B} ({score:.1f}{metric} on {benchmark})
           - If no directly comparable common benchmark evidence exists across all replace challengers:
             - Output: "{Model A} / {Model B} all outperform current incumbent; insufficient comparable evidence to rank them reliably."
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
                return f"Retain {current_incumbent} (Leads not worth switching)"
            return f"Retain {current_incumbent}"

        if len(replace_yes_reports) == 1:
            return f"**{replace_yes_reports[0].model.display_name}** (Replace: Yes)"

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
                has_harness_issue = any("harness" in (u or "").lower() for u in uncertainties)
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
                return f"Tie: {' / '.join(tied)} ({top_score:.1f}{metric_str} on {benchmark})"
            else:
                return f"**{top_name}** ({top_score:.1f}{metric_str} on {benchmark})"

        # No common benchmark among Replace: Yes candidates
        names_sorted = sorted([r.model.display_name for r in replace_yes_reports])
        return f"{' / '.join(names_sorted)} all outperform current incumbent; insufficient comparable evidence to rank them reliably."

    def save_comparison_report(self, content: str, tag: str = "comparison") -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        safe_tag = tag.replace("/", "_").replace(":", "_").replace(" ", "_")
        filename = f"{date_str}_{safe_tag}.md"
        out_path = self.reports_dir / filename
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        return out_path
