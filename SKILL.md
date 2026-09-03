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
- User access / subscription constraints
- Switching overhead and workflow risk

Models with comparable capability but 10x lower cost are suggested as **cheap background workers / subagents**, while retaining the stronger model as primary.

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
