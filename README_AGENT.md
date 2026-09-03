# Model Watcher — Agent Deployment & Integration Guide

> **Notice for AI Agents (OpenClaw, Hermes, Antigravity, Claude Code, etc.):**  
> This document is optimized for machine interpretation and automated agent deployment. It specifies execution modes, tool calling contracts, error handling, and scheduled integration.

---

## 1. System Overview

- **Binary Name:** `model-watcher` (CLI wrapper in `./bin/model-watcher`)
- **Execution Architecture:** Pure run-once CLI tool. **Zero daemons, zero background cron jobs, zero web servers.**
- **Core Function:** Evaluates AI models head-to-head against the user's active 7-role baseline division of labor (`profile.yaml`) using structured benchmark evidence (SWE-bench, LiveBench, Harbor Hub, Artificial Analysis).

---

## 2. Agent 3-Step Deployment Protocol

```bash
# Step 1: Install environment dependencies using uv (or standard pip)
git clone https://github.com/bilppppp/model-watcher.git
cd model-watcher
uv sync

# Step 2: Establish User Baseline Calibration Profile
# A. For non-interactive automated deployment (e.g. CI/agent runner):
cp profile.yaml.example profile.yaml
# B. For interactive user interview:
./bin/model-watcher calibrate

# Step 3: Verify Deployment
./bin/model-watcher status
```

### Environment Variables (Optional in `.env`)
Place optional API keys in `.env` (permissions `chmod 600`, auto-ignored by Git):
```bash
ARTIFICIAL_ANALYSIS_API_KEY="aa_..."   # Optional: fetches 200+ models, live pricing & release dates
HARBOR_API_KEY="sk-harbor-..."         # Optional: fetches Harbor Hub Terminal-Bench leaderboards
```
*Note: If keys are missing, Model Watcher automatically and gracefully falls back to public repositories (LiveBench, SWE-bench).*

---

## 3. Machine-Actionable Tool Contracts

### Command Matrix

| CLI Command | Purpose | Mutates `state.json`? | Requires Release Date? | Exit Code |
|---|---|---|---|---|
| `./bin/model-watcher compare <MODEL...>` | On-demand model evaluation & cross-model summary | **NO** (Pure read-only) | **NO** (Any historical/frontier model) | 0: Success<br>1: Model not found<br>2: Missing profile |
| `./bin/model-watcher run` | Continuous monitor check (new models) | **YES** (`NEW`→`PROVISIONAL`→`MATURE`) | **YES** (60-day window) | 0: Up-to-date / Done<br>2: Missing profile |
| `./bin/model-watcher calibrate` | Guided baseline recalibration | **NO** (Only updates `profile.yaml`) | **NO** | 0: Success |
| `./bin/model-watcher status` | Inspection of calibration revision & state | **NO** | **NO** | 0: Success |

---

## 4. Agent Intent Routing Guidelines

When parsing natural language user prompts, route directly to the corresponding command:

```
User Prompt Pattern                                    Action / Command
---------------------------------------------------    -------------------------------------------------------
"Compare Gemini 3.8 and Claude Opus"                   ./bin/model-watcher compare "gemini-3.8-flash" "claude-opus-5"
"Is GPT-4o better than my current coder?"              ./bin/model-watcher compare "gpt-4o"
"Evaluate whether X can replace my reviewer"           ./bin/model-watcher compare "X"
"Check for new models" / "Run daily monitor"           ./bin/model-watcher run
"I upgraded my models" / "Update my baseline profile"  ./bin/model-watcher calibrate
"What models am I currently using?"                    ./bin/model-watcher status
```

---

## 5. Decision Logic & Constraints for Agents

1. **Reviewer Golden Rule**:
   - Model Watcher **never** extrapolates reviewer capabilities from coding or reasoning scores.
   - If direct bug-finding / code-review evidence is absent, output is strictly `? Insufficient evidence` and `Replace: No`.
2. **Order-Invariance in Multi-Model Comparison**:
   - Running `./bin/model-watcher compare A B` and `./bin/model-watcher compare B A` produces identical recommendation verdicts.
   - If multiple challengers beat the current incumbent but lack common comparable benchmarks, output is strictly:
     `"<A> / <B> all outperform current incumbent; insufficient comparable evidence to rank them reliably."`
3. **Non-Interactive Safety Gating (Exit Code 2)**:
   - If `profile.yaml` is missing in a non-interactive shell, Model Watcher **will not guess** a baseline. It exits with code `2` (`NEEDS_CALIBRATION`).
   - The calling agent must prompt the user or initialize `profile.yaml` from `profile.yaml.example`.

---

## 6. Output & Report Artifacts

- **Console Output:** Clean GitHub Flavored Markdown table and verdict printed to `stdout`.
- **File Artifacts:** Automatically saved under `reports/` (ignored by Git):
  - Single evaluation: `reports/YYYY-MM-DD_<model-id>.md`
  - Cross-model compare: `reports/YYYY-MM-DD_compare_<modelA>_vs_<modelB>.md`

---

## 7. External Automation Examples

### Cron Integration (Daily Check at 08:00)
```crontab
0 8 * * * cd /path/to/model-report && ./bin/model-watcher run >> /var/log/model-watcher.log 2>&1
```

### OpenClaw / Hermes Subagent Script
```bash
#!/usr/bin/env bash
set -e
# Run compare and capture report
OUTPUT=$(./bin/model-watcher compare "claude-3-5-sonnet" "gpt-4o")
echo "$OUTPUT"
```
