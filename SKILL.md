---
name: model-watcher
description: Autonomous frontier AI model monitor. Evaluates whether new mainstream models alter the user's current 7-role workflow routing (Coder, Planner, Reviewer, Reasoner, Analyst, Agent, Multimodal) against active incumbents using machine-readable benchmark evidence (SWE-bench, LiveBench, Harbor Hub, Artificial Analysis). Run-once, idempotent, produces 30s actionable reports.
---

# Model Watcher

Model Watcher is not an AI news digest, nor a generic benchmark leaderboard.

It answers one specific question:

> Has a new mainstream AI model appeared recently? If so, does it justify changing the user's current 7-role model division of labor?

Every challenger is evaluated head-to-head against the user's actual **incumbent** models across 7 fixed operational roles, rather than evaluating models in isolation.

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

## User Baseline Profile (`profile.yaml`)

Persists user's current model allocation:
- Accessible / owned models
- Primary incumbent for each of the 7 roles
- Fallback models
- Constraints (cost sensitivity, budget, preferred providers)

**Zero Silent Modification**: Model Watcher only proposes `Role: A → B` adjustment recommendations. It never modifies `profile.yaml` without explicit user confirmation.

If `profile.yaml` is missing on first run, Model Watcher launches a guided initialization flow asking one question at a time.

---

## State Persistence (`state.json`)

Simple, database-free JSON state:
- Model canonical ID & display name
- Provider
- `first_seen` & `evaluated_at`
- Lifecycle Status: `NEW` → `PROVISIONAL` → `MATURE`
- Reference to generated report

### Lifecycle Rules
1. **First Seen**: Evaluated immediately as `PROVISIONAL`.
2. **~7 Days Later**: Eligible for one mature review to reach `MATURE`.
3. **Mature**: Never repeated on subsequent runs unless major new evidence emerges.
4. **Idempotence**: Running multiple times without new models exits cleanly and quickly.

---

## Data Source Hierarchy

- **P0**: Official machine-readable benchmark results
  - **LiveBench**: `LiveBench/new-livebench` public repository (`table_<date>.csv`, `categories_<date>.json`)
  - **SWE-bench**: `SWE-bench/swe-bench.github.io` (`data/leaderboards.json`)
  - **Harbor Hub**: Official CLI `harbor hub leaderboard show <id> --json` (Terminal-Bench 2.0 / 4.0 / 2.1)
- **P1**: Independent standardized benchmarks
  - **Artificial Analysis**: Data API v2 (`GET /language/models/free`, auth via `x-api-key`)
  - **LMMs-Eval**: Official benchmark suites for multimodal evaluations
- **P2**: Official model cards and release notes
- **P3**: Reproducible 3rd-party evals
- **P4**: Trusted community production feedback
- **P5**: Media / secondary information

---

## CLI Usage

Run once (designed to be invoked by external schedulers or on-demand):

```bash
# Standard single execution
./bin/model-watcher run
# or
uv run python3 -m model_watcher.cli run

# Check status of baseline and tracked models
./bin/model-watcher status

# Force dry-run evaluation on a specific frontier model
./bin/model-watcher run --model "claude-opus-4-7" --dry-run
```

Reports are stored in:
`reports/YYYY-MM-DD_<model-id>.md`
