# 🆕 Doubao-Seed-Code

**结论：** 可以忽略
**本次改变：0/7 个当前模型路由**

> 已完成评估，没有任何维度足以改变当前模型组合，可以忽略这次发布。

| Role | Current | Challenger | Capability | Replace? |
|---|---|---|---|---|
| Coder / Builder | claude-3-7-sonnet | Doubao-Seed-Code | ↗ Probably better | No |
| Planner | claude-3-7-sonnet | Doubao-Seed-Code | ? Insufficient evidence | No |
| Reviewer | claude-3-7-sonnet | Doubao-Seed-Code | ? Insufficient evidence | No |
| Reasoner | o3-mini | Doubao-Seed-Code | ? Insufficient evidence | No |
| Analyst / Researcher | claude-3-7-sonnet | Doubao-Seed-Code | ? Insufficient evidence | No |
| Agent / Computer-use | claude-3-7-sonnet | Doubao-Seed-Code | ? Insufficient evidence | No |
| Multimodal | gemini-2.5-pro | Doubao-Seed-Code | ? Insufficient evidence | No |

## 建议调整

无路由调整建议。当前组合保持最优。

## 保持不动

- **Coder / Builder (claude-3-7-sonnet)**: Marginal lead (+3.6% resolved) is insufficient to justify migration and switching overhead.
- **Planner (claude-3-7-sonnet)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.
- **Reviewer (claude-3-7-sonnet)**: No direct code-review or adversarial bug-finding benchmark evidence. Reviewer requires strict direct evidence; retaining incumbent.
- **Reasoner (o3-mini)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.
- **Analyst / Researcher (claude-3-7-sonnet)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.
- **Agent / Computer-use (claude-3-7-sonnet)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.
- **Multimodal (gemini-2.5-pro)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.

## 新用途

- Specialist builder for high-difficulty coding issues

## 最值得知道的一点

Finished evaluation: no dimension sufficiently alters current model routing; safe to ignore this release.

## Evidence / Confidence

- **Source:** SWE-bench | **Benchmark:** SWE-bench Verified (verified-v1)
  - **Score:** Challenger: 78.8% resolved vs Incumbent: 75.2% resolved
  - **Harness:** TRAE
  - **URL:** https://www.swebench.com
  - **Confidence:** 85%
  - **Uncertainty:** Official verified benchmark submission
