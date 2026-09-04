---
name: model-watcher
description: Autonomous frontier AI model monitor and on-demand comparator. Evaluates whether new mainstream models alter the user's current 7-role workflow routing (Coder, Planner, Reviewer, Reasoner, Analyst, Agent, Multimodal) against active calibrated incumbents using machine-readable benchmark evidence (SWE-bench, LiveBench, Harbor Hub, Artificial Analysis). Supports run (monitor), compare (on-demand comparison), and calibrate (lifecycle baseline update).
---

# Model Watcher

Model Watcher is not an AI news digest, nor a generic benchmark leaderboard.

It answers one specific question:

> Has a new mainstream AI model appeared recently? If so, does it justify changing the user's current 7-role model division of labor?

Every challenger is evaluated head-to-head against the user's actual **calibrated incumbent** models across 7 fixed operational roles, rather than evaluating models in isolation.

---

## Default Language Policy (Simplified Chinese)

All reports produced by Model Watcher (Markdown reports, tables, headers, rationales, takeaways, and cross-model summaries) natively output **Simplified Chinese** (`zh-CN`) by default.
- Agents interacting with the user MUST present these reports in Simplified Chinese directly as generated.
- Only when the user explicitly requests another language (e.g., English) should the Agent convert the report at the presentation layer.
- Technical benchmarks, model IDs, source names, harness names, URLs, and metric units remain in their original canonical forms without translation.

---

## Natural Language Intent Mapping

When the user gives instructions to the Agent:

### 1. Monitor Intent
*Examples:*
- "检查有没有新模型"
- "最近模型发布有没有改变我的选择"
- "运行一次监控"
- "看看今天有没有值得换的模型"

→ Execute: `./bin/model-watcher run`

### 2. Compare Intent
*Examples:*
- "比较 Gemini 3.8 Flash 和 Sol"
- "帮我评估 Opus 5"
- "这三个模型我应该怎么分工"
- "对比 A、B、C"
- "Claude 3.7 Sonnet 和 GPT-4o 谁更适合做我的 Coder"

→ Execute: `./bin/model-watcher compare MODEL [MODEL ...]`

### 3. Calibration Intent
*Examples:*
- "我换模型了"
- "更新一下我现在用的模型"
- "重新校准"
- "我现在有 A、B、C"
- "我的当前主力模型变了"

→ Execute: `./bin/model-watcher calibrate`

> [!IMPORTANT]
> **No Guessing**: If any `compare` or `run` command discovers that no valid calibration profile (`profile.yaml`) exists, Model Watcher will **not** guess or fabricate a baseline. It will require the user to complete calibration first (`./bin/model-watcher calibrate`).

---

## 7 Fixed Operational Roles

1. **Coder / Builder**
   - Repo coding, implementation, issue fixing, debugging
   - *Key Evidence*: SWE-bench Verified, DeepSWE, LiveBench Coding

2. **Planner**
   - Architecture, task decomposition, long-horizon planning, orchestration
   - *Key Evidence*: Long-horizon agent evals, complex workflow benchmarks

3. **Reviewer**
   - Code review, bug finding, adversarial review, incorrect assumptions
   - *Key Evidence*: Dedicated code review benchmarks, bug-finding evals
   - **Reviewer Golden Rule**: Lacking direct code review evidence must output `? Insufficient evidence`. Never extrapolate from reasoning or coding scores.

4. **Reasoner**
   - Logic, mathematics, algorithms, scientific reasoning
   - *Key Evidence*: LiveBench Reasoning & Mathematics, HLE, GPQA

5. **Analyst / Researcher**
   - Research, knowledge work, synthesis, documents / data, professional reports
   - *Key Evidence*: LiveBench Data Analysis, GDPVal

6. **Agent / Computer-use**
   - Terminal, tools, autonomous execution, long workflows, error recovery, GUI/browser
   - *Key Evidence*: Terminal-Bench (2.0 / 4.0 / 2.1 via Harbor Hub), LiveBench Agentic Coding

7. **Multimodal**
   - Images, PDFs, charts, video, mixed media
   - *Key Evidence*: MMMU / MMMU-Pro, MathVista, LMMs-Eval

---

## Verdict System

### Capability Verdict
- `↑ Clearly better` (delta >= +5.0% or statistically superior)
- `↗ Probably better` (delta +1.5% to +5.0%)
- `= No meaningful advantage` (-1.5% <= delta < +1.5%)
- `↘ Probably worse` (delta < -1.5%)
- `? Insufficient evidence` (no direct evidence; strictly required for Reviewer when absent)

### Replacement Verdict
- `Replace? Yes / No`

Capability superiority and replacement recommendation are strictly separated. Marginal improvements do not trigger replacement. Replacement accounts for:
- Verified margin size
- Evidence reliability and harness comparability
- Token pricing, latency, context limits
- Switching overhead and workflow risk
*(Note: User access / subscription constraints are evaluated and displayed independently via "当前可用性", and do not block a Replace: Yes verdict).*

Models with comparable capability but 10x lower cost are suggested as **cheap background workers / subagents**, while retaining the stronger model as primary.

---

## Report Presentation & Decision Readability Policy

> **Core Principle**: “有答案的内容成为主体；没有答案的角色透明披露，但不得淹没真正的决策信息。”

When presenting Model Watcher findings or summarizing reports to the user, Agents MUST strictly adhere to the following decision-first presentation rules:

### 1. Top 20 Lines Directly Answer the User's Questions
The opening lines of the report/presentation must immediately tell the user:
- **这个新模型值得换吗？**（结论：建议加入 / 部分替换 / 值得关注，暂不调整 / 可以忽略）
- **建议调整：** X 个角色
- **有效评估：** Y/7 个角色（基于真实可比证据已完成判定的角色数，绝不给用户造成全部 7 角色均已评估的错觉）
- **当前可用性：** 已配置 / 未配置（未列入当前 Calibration）
- **当前校准基线：** Revision N

### 2. “一眼看懂” (At a Glance)
Immediately following the headline/table, provide a high-signal executive summary:
- **上限 3~5 条**：只写真正影响决策的实质性发现（如建议替换项、显著领先但受限于非直接基准的暂缓项、极低成本子工推荐等）。
- **绝不填充未评估项**：`暂未判断` / `证据不足` 的角色严禁占据“一眼看懂”。
- **无新信号写一句明确结论**：如果没有值得关注的新发现，直接输出单句定论（如“评估完成：没有发现足以改变当前工作流的信号，可以安全忽略本次发布。”），切忌硬凑 3~5 条废话。

### 3. 三类结果语义严格区分
- **建议调整 (Replace == Yes)**：现有证据足以支持该模型成为这一角色的更优主力。当前是否已配置作为独立的获取条件展示，不得因为“未配置”将 Replace Yes 改写为 No。
- **明确保留 (已评估，Replace == No)**：已有充分的同环境可比证据，但领先幅度微弱（<1.5%）、落后或受限于 Composite Index 不确定性，明确建议保留当前主力。
- **暂未判断 (Capability == Insufficient Evidence)**：明确表述为“本次暂无可靠直接证据判断该角色，不据此做出任何路由调整。”
  > [!IMPORTANT]
  > **严禁将“证据不足”描述为“已经证明应该保留当前模型”**。没有证据就是没有证据，不能伪造成保留的积极理由。

### 4. 有效评估结果优先展示
- 核心决策表格只展示完成了有效评估的角色：
  `| 角色 | 当前模型 | 能力判断 | 建议 |`
- 建议列使用简明自然语言：`建议替换`、`保留`、`暂不切换，继续观察`。
- 因整份报告针对同一候选模型，表格中无需每行重复候选模型名称。

### 5. 暂未判断透明披露并降低视觉权重
- 缺乏证据的角色（如当前缺乏公开直接评测的规划、审查、多模态）统一放置在后部的 `## 暂未判断` 章节。
- 简明说明各自的数据缺失原因（例如：审查角色严格遵循 Reviewer Golden Rule，不以纯编码或推理指标推断），不遮掩缺失，但严禁在主表中连续输出 3~4 行 `? 证据不足` 制造视觉污染。

### 6. “保持不动”避免同质化模板
- 避免机械式逐行重复“角色 X：保留 xxx（……）”。
- 遇到多个角色因同类原因保留时，进行归纳合并（例如：“编码与推理：保留当前主力（候选模型在对应基准上无显著优势）”），直接突出核心决策依据。

---

## Current Calibration (`profile.yaml`)

Persists user's current model allocation with formal calibration metadata:
- `revision: <int>` (increments +1 on every confirmed recalibration)
- `calibrated_at: <ISO timestamp>`
- Accessible / owned models
- Primary incumbent for each of the 7 roles
- Fallback models
- Constraints (cost sensitivity, budget, preferred providers)

**Zero Silent Modification**: Model Watcher only proposes `Role: A → B` adjustment recommendations. It never modifies `profile.yaml` without explicit user confirmation during the recalibration diff review.

---

## On-Demand Compare (`compare MODEL [MODEL ...]`)

Semantic separation from Monitor:
- Does **not** require candidate to be a recent release
- Does **not** pass through the 60-day release gate
- Does **not** require release date confirmation
- Does **not** modify `state.json` or alter model lifecycle states
- Re-reads latest benchmark evidence and compares against current calibration revision
- Produces individual role comparison reports plus a **Cross-Model Role Summary Table** for multi-model queries:
  `| Role | Current | Model A | Model B | Model C | Recommendation |`

---

## CLI Usage

```bash
# 1. On-demand Model Compare (single or multi-model)
./bin/model-watcher compare "gemini-3.8-flash"
./bin/model-watcher compare "gemini-3.8-flash" "gpt-5.6-sol" "claude-opus-5"

# 2. Recalibrate Baseline Routing
./bin/model-watcher calibrate

# 3. Monitor Check (Single idempotent run for external schedulers)
./bin/model-watcher run

# 4. View Current Status & Calibration
./bin/model-watcher status
```

Reports are stored in:
- Monitor: `reports/YYYY-MM-DD_<model-id>.md`
- Compare: `reports/YYYY-MM-DD_compare_<tag>.md`
