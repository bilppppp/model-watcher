"""Report generation formatting crisp 30-second markdown briefings."""
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import List

from model_watcher.types import EvaluationReport, ReplaceVerdict, Role


class MarkdownReporter:
    def __init__(self, reports_dir: Path = Path("reports")):
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def format_report(self, report: EvaluationReport) -> str:
        model_name = report.model.display_name or report.model.canonical_id
        lines = []

        lines.append(f"# 🆕 {model_name}\n")
        lines.append(f"**结论：** {report.overall_verdict}")
        lines.append(f"**本次改变：{report.routes_changed}/{report.total_routes} 个当前模型路由**\n")

        if report.routes_changed == 0:
            lines.append("> 已完成评估，没有任何维度足以改变当前模型组合，可以忽略这次发布。\n")

        # Table of 7 roles
        lines.append("| Role | Current | Challenger | Capability | Replace? |")
        lines.append("|---|---|---|---|---|")
        for role in Role:
            ev = report.role_evaluations.get(role)
            if ev:
                lines.append(f"| {role.display_name} | {ev.incumbent_model} | {ev.challenger_model} | {ev.capability.value} | {ev.replace.value} |")
            else:
                lines.append(f"| {role.display_name} | - | {model_name} | ? Insufficient evidence | No |")
        lines.append("")

        # 建议调整
        lines.append("## 建议调整\n")
        replacements = [ev for ev in report.role_evaluations.values() if ev.replace == ReplaceVerdict.YES]
        if replacements:
            for rep in replacements:
                lines.append(f"{rep.role.display_name}:")
                lines.append(f"{rep.incumbent_model} → {rep.challenger_model}\n")
        else:
            lines.append("无路由调整建议。当前组合保持最优。\n")

        # 保持不动
        lines.append("## 保持不动\n")
        non_replacements = [ev for ev in report.role_evaluations.values() if ev.replace == ReplaceVerdict.NO]
        if non_replacements:
            for ev in non_replacements:
                lines.append(f"- **{ev.role.display_name} ({ev.incumbent_model})**: {ev.replace_rationale}")
            lines.append("")
        else:
            lines.append("所有主要路由均建议切换。\n")

        # 新用途
        lines.append("## 新用途\n")
        if report.new_use_cases:
            for u in report.new_use_cases:
                lines.append(f"- {u}")
            lines.append("")
        else:
            lines.append("- 暂无额外专有角色建议。\n")

        # 最值得知道的一点
        lines.append("## 最值得知道的一点\n")
        lines.append(f"{report.key_takeaway}\n")

        # Evidence / Confidence
        lines.append("## Evidence / Confidence\n")
        if report.evidence_ledger:
            seen = set()
            for e in report.evidence_ledger:
                key = f"{e.source}_{e.benchmark}"
                if key in seen:
                    continue
                seen.add(key)

                score_str = f"Challenger: {e.score_challenger}{e.display_metric}" if e.score_challenger is not None else "N/A"
                if e.score_incumbent is not None:
                    score_str += f" vs Incumbent: {e.score_incumbent}{e.display_metric}"

                lines.append(f"- **Source:** {e.source} | **Benchmark:** {e.benchmark} ({e.version})")
                lines.append(f"  - **Score:** {score_str}")
                lines.append(f"  - **Harness:** {e.harness}")
                lines.append(f"  - **URL:** {e.url}")
                lines.append(f"  - **Confidence:** {int(e.confidence * 100)}%")
                if e.known_uncertainty:
                    lines.append(f"  - **Uncertainty:** {e.known_uncertainty}")
                lines.append("")
        else:
            lines.append("- 缺乏独立公开的标准化基准测试分数；暂无高置信度核心证据。\n")

        return "\n".join(lines)

    def save_report(self, report: EvaluationReport) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        safe_id = report.model.canonical_id.lower().replace("/", "-").replace(":", "-")
        filename = f"{date_str}_{safe_id}.md"
        path = self.reports_dir / filename

        content = self.format_report(report)
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_path, path)

        return path
