# Model Watcher

> **Autonomous Frontier AI Model Routing Monitor**
> 
> Continuous evaluation of newly released mainstream AI models to decide whether they alter the user's active 7-role workflow routing against existing incumbents.

---

## What Model Watcher Does

Model Watcher is not an AI news digest, nor a generic benchmark leaderboard. It answers one core question:

> **Has a new mainstream AI model appeared recently? If so, does it justify changing the user's current 7-role model division of labor?**

Every challenger is evaluated head-to-head against the user's active **incumbent** models using structured, machine-readable benchmark evidence.

---

## The 7 Fixed Roles

1. **Coder / Builder**: Repo coding, implementation, issue fixing, debugging (Primary: SWE-bench Verified, LiveBench Coding, DeepSWE).
2. **Planner**: Architecture, task decomposition, long-horizon planning, orchestration.
3. **Reviewer**: Code review, bug finding, adversarial review.
   - *Reviewer Golden Rule*: If direct code-review evidence is missing, outputs `? Insufficient evidence`. Never guess.
4. **Reasoner**: Logic, mathematics, algorithms, scientific reasoning (Primary: LiveBench Reasoning & Mathematics, HLE, GPQA).
5. **Analyst / Researcher**: Research, knowledge work, synthesis, data analysis (Primary: LiveBench Data Analysis, GDPVal).
6. **Agent / Computer-use**: Terminal execution, tool calling, autonomous workflows (Primary: Terminal-Bench 2.0/4.0/2.1 via Harbor Hub, LiveBench Agentic Coding).
7. **Multimodal**: Images, PDFs, charts, video, mixed media (Primary: MMMU, MathVista, LMMs-Eval).

---

## Verdict & Replacement Principles

- **Capability Verdicts**:
  - `↑ Clearly better` (delta >= +5.0%)
  - `↗ Probably better` (delta +1.5% to +5.0%)
  - `= No meaningful advantage` (-1.5% <= delta < +1.5%)
  - `↘ Probably worse` (delta < -1.5%)
  - `? Insufficient evidence` (no direct evidence; strictly required for Reviewer when absent)
- **Replace?**: `Yes` / `No`
  - Capability superiority and replacement recommendations are distinct.
  - Marginal advantages do not trigger replacement by default.
  - Factors evaluated: margin size, harness comparability, pricing, latency, context limits, user subscription access, and migration risk.
  - Comparable models with 10x lower cost are suggested as **cheap background workers / subagents**, while retaining the stronger model as primary commander.

---

## Project Structure

```
model-report/
├── SKILL.md                          # Antigravity Skill definition
├── manifest.json                     # Skill metadata
├── profile.yaml                      # Active user baseline profile
├── profile.yaml.example              # Baseline profile template
├── state.json                        # Persistent state (tracks 160+ models)
├── reports/                          # Generated 30s markdown reports
│   └── 2026-09-03_claude-opus-4-7...md
├── references/
│   ├── sources.yaml                  # Official data source registry & priorities
│   └── roles.yaml                    # 7-role task & benchmark specifications
├── bin/
│   └── model-watcher                 # Standalone executable CLI wrapper
├── src/
│   └── model_watcher/
│       ├── cli.py                    # CLI entrypoint
│       ├── config.py                 # Profile management & interactive init
│       ├── state.py                  # State persistence, atomic writes & lifecycle
│       ├── types.py                  # Domain models, Enums, dataclasses
│       ├── aggregator.py             # Candidate discovery & evidence collection
│       ├── evaluator.py              # Comparative 7-role evaluation engine
│       ├── reporter.py               # 30-second markdown report formatter
│       └── sources/
│           ├── livebench.py          # LiveBench official repo reader
│           ├── swebench.py           # SWE-bench official repo reader
│           ├── harbor.py             # Harbor Hub official CLI reader
│           ├── artificial_analysis.py# Artificial Analysis v2 API reader
│           └── lmms_eval.py          # LMMs-Eval multimodal reader
└── tests/                            # Comprehensive unit & integration tests
```

---

## Quickstart

### 1. Initialize Baseline Profile

If running for the first time, establish your model usage baseline:

```bash
# Interactive guided setup (asks questions one-by-one)
./bin/model-watcher init

# Or initialize with default baseline template
./bin/model-watcher init --defaults
```

### 2. Check Status

```bash
./bin/model-watcher status
```

### 3. Run Single Cycle

Designed to be called once by an external scheduler (cron, systemd timer, launchd, or manual invocation):

```bash
# Standard single execution: discovers new models, evaluates, updates state, exits
./bin/model-watcher run

# Verbose output (displays confirmation even if up-to-date)
./bin/model-watcher run --verbose

# Dry-run evaluation on a specific frontier model
./bin/model-watcher run --model "claude-opus-4-7" --dry-run
```

---

## Data Source Configurations

Model Watcher adheres to the P0-P5 priority hierarchy:

1. **LiveBench (P0)**: Public repo `LiveBench/new-livebench` (`table_<date>.csv`, `categories_<date>.json`). Dynamically resolves latest release.
2. **SWE-bench (P0)**: Official repo `SWE-bench/swe-bench.github.io` (`data/leaderboards.json`). Reads Verified leaderboard.
3. **Harbor Hub (P0)**: CLI `harbor hub leaderboard show <id> --json`. Reads Terminal-Bench 2.0 / 4.0 / 2.1 datasets.
4. **Artificial Analysis (P1)**: Data API v2 (`GET /language/models/free`). Requires `ARTIFICIAL_ANALYSIS_API_KEY` in environment. If missing, gracefully skips without error.
5. **LMMs-Eval (P1)**: Official multimodal evaluations (MMMU, MathVista).

---

## Running Tests

Run the full test suite covering all 12 validation requirements:

```bash
uv run python3 -m unittest discover -s tests -v
```
