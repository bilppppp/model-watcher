# 🆕 Qwen 3 Coder 480B

**结论：** 可以忽略
**本次改变：0/7 个当前模型路由**

> 已完成评估，没有任何维度足以改变当前模型组合，可以忽略这次发布。

| Role | Current | Challenger | Capability | Replace? |
|---|---|---|---|---|
| Coder / Builder | claude-3-7-sonnet | Qwen 3 Coder 480B | ↘ Probably worse | No |
| Planner | claude-3-7-sonnet | Qwen 3 Coder 480B | ? Insufficient evidence | No |
| Reviewer | claude-3-7-sonnet | Qwen 3 Coder 480B | ? Insufficient evidence | No |
| Reasoner | o3-mini | Qwen 3 Coder 480B | ? Insufficient evidence | No |
| Analyst / Researcher | claude-3-7-sonnet | Qwen 3 Coder 480B | ? Insufficient evidence | No |
| Agent / Computer-use | claude-3-7-sonnet | Qwen 3 Coder 480B | = No meaningful advantage | No |
| Multimodal | gemini-2.5-pro | Qwen 3 Coder 480B | ? Insufficient evidence | No |

## 建议调整

无路由调整建议。当前组合保持最优。

## 保持不动

- **Coder / Builder (claude-3-7-sonnet)**: Challenger shows no meaningful capability edge over claude-3-7-sonnet (delta: -5.6% resolved).
- **Planner (claude-3-7-sonnet)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.
- **Reviewer (claude-3-7-sonnet)**: No direct code-review or adversarial bug-finding benchmark evidence. Reviewer requires strict direct evidence; retaining incumbent.
- **Reasoner (o3-mini)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.
- **Analyst / Researcher (claude-3-7-sonnet)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.
- **Agent / Computer-use (claude-3-7-sonnet)**: Challenger score is moderate without direct incumbent head-to-head comparison.
- **Multimodal (gemini-2.5-pro)**: No verifiable comparative benchmark evidence available for this role; retaining incumbent.

## 新用途

- 暂无额外专有角色建议。

## 最值得知道的一点

Finished evaluation: no dimension sufficiently alters current model routing; safe to ignore this release.

## Evidence / Confidence

- **Source:** SWE-bench | **Benchmark:** SWE-bench Verified (verified-v1)
  - **Score:** Challenger: 69.6% resolved vs Incumbent: 75.2% resolved
  - **Harness:** OpenHands
  - **URL:** https://www.swebench.com
  - **Confidence:** 75%
  - **Uncertainty:** Different harness: challenger on OpenHands, incumbent on TRAE

- **Source:** Harbor Hub | **Benchmark:** Terminal-Bench 2.0 (v2)
  - **Score:** Challenger: 27.19%
  - **Harness:** Dakou Agent
  - **URL:** https://hub.harborframework.com
  - **Confidence:** 85%
  - **Uncertainty:** Harbor Hub curated benchmark run
