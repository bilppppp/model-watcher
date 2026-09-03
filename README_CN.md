# Model Watcher

> **前沿主流大模型路由监控与按需对决评估器**
> 
> 基于客观结构化 Benchmark 证据，评估新发布的或指定的前沿 AI 模型是否足以改变用户当前在 7 个核心岗位上的主力分工。

---

## 🎯 产品核心目标

Model Watcher **不是** AI 新闻摘要器，也**不是**通用的 Benchmark 排行榜。

它只回答一个核心问题：

> **最近是否出现了新的主流 AI 模型？如果有，它是否足以改变我当前的模型使用分工？**

任何候选模型都必须与用户当前实际正在使用的 **Incumbent（在位主力模型）** 在 7 个固定业务角色上进行一对一实证对比，而不是脱离业务孤立评价模型本身。

---

## 👥 7 大固定业务角色体系

1. **Coder / Builder（代码构建）**
   - 仓库级编码、功能实现、Issue 修复、测试与 Debug
   - *核心证据源*：SWE-bench Verified、DeepSWE、LiveBench Coding
2. **Planner（架构规划）**
   - 系统架构设计、长程任务拆解、多 Agent 协作编排
   - *核心证据源*：长程 Agent 基准测试、复杂工作流评测
3. **Reviewer（代码审查）**
   - 深入代码 Review、对抗性缺陷挖掘、反直觉假设纠偏
   - **Reviewer Golden Rule（黄金准则）**：缺乏直接的代码审查与 Bug-finding 测试数据时，必须返回 `? Insufficient evidence`，绝对禁止根据编码或通用推理分数主观推测。
4. **Reasoner（深度推理）**
   - 复杂数学、算法设计、严密逻辑链推演、科学计算
   - *核心证据源*：LiveBench Reasoning & Mathematics、HLE、GPQA
5. **Analyst / Researcher（分析研究）**
   - 深度信息调研、知识合成、多维数据分析、研报撰写
   - *核心证据源*：LiveBench Data Analysis、GDPVal
6. **Agent / Computer-use（终端与工具执行）**
   - 命令行终端、工具调用、自主长流程、错误自愈、GUI/浏览器控制
   - *核心证据源*：Harbor Hub 评测体系（Terminal-Bench 2.0 / 4.0 / 2.1）、LiveBench Agentic Coding
7. **Multimodal（多模态处理）**
   - 图像、图表、PDF 文档、视频混合媒介理解
   - *核心证据源*：MMMU / MMMU-Pro、MathVista、LMMs-Eval

---

## ⚖️ 裁决体系与替换准则

### 1. 能力评估结论（Capability Verdict）
- `↑ Clearly better`（相对在位模型领先 >= +5.0%）
- `↗ Probably better`（微弱领先 +1.5% ~ +5.0%）
- `= No meaningful advantage`（无显著差异，-1.5% ~ +1.5%）
- `↘ Probably worse`（落后 < -1.5%）
- `? Insufficient evidence`（证据不足，禁止主观推测）

### 2. 替换推荐结论（Replace? Yes / No）
能力领先 **不等于** 立即替换主力。微小优势不触发迁移风险。系统综合考量：
- 领先幅度与证据可信度
- 测试 Harness 是否具备严谨同等可比性
- API 输入/输出定价、吞吐速率（Tokens/s）
- 用户实际订阅与模型可访问性权限
- 迁移成本与工作流破坏风险

**极低成本智能分流**：对于性能持平但单价便宜 10 倍的模型，系统自动建议设立新用途：`Cheap background worker / subagent`（作为高并发低成本执行工），而保留最强模型作为主脑。

---

## 🚀 核心功能与使用指南

系统设计为**单次运行即退出（Run-and-exit）**的轻量 CLI，无需启动任何后台常驻 Daemon、Web 服务或轮询进程，专供人工或外部调度器（如 Cron、CI、Agent 框架）调用。

### 1. 首次初始化与校准（Calibration Lifecycle）

Model Watcher 的所有裁决均基于用户最新真实的模型基准 `profile.yaml`：

```bash
# 方式 A：交互式引导校准（逐题确认当前主力模型）
./bin/model-watcher calibrate

# 方式 B：使用标准基准模板初始化（测试/CI自动化使用）
./bin/model-watcher init --defaults
```

> [!IMPORTANT]
> **非交互模式防误判（Exit Code 2）**：在缺少 `profile.yaml` 的非交互自动化环境下，系统绝不会擅自猜测预设旧模型，而是直接输出错误指引并返回状态码 `2`，强制要求先确立真实基线。

### 2. 按需模型对比（On-demand Compare）

支持随时对任意模型（不受发布时间或 60 天窗口限制）发起与当前校准基线的一对一或多对一评估，**不会修改内部追踪状态机**：

```bash
# 单模型对比：挑战当前 7 角色在位主力
./bin/model-watcher compare "gemini-2.5-pro"

# 多模型对决：分别挑战 + 输出跨模型角色总结表
./bin/model-watcher compare "claude-3-5-sonnet" "gpt-4o"
```

#### 跨模型推荐表（输入顺序严格无关）
当多个候选模型同时挑战成功时，系统仅在具备相同 Benchmark、相同版本、相同 Harness 时推选最高分；若各具不同优势但无直接同等基准，明确说明证据不充分，拒绝因命令参数顺序选出假赢家：

```markdown
# 📊 Cross-Model Comparison Summary

**Baseline Calibration:** Revision 1 (Initial)

| Role | Current | Claude 3.5 Sonnet | GPT-4o | Recommendation |
|---|---|---|---|---|
| Coder / Builder | claude-3-7-sonnet | ↘ Probably worse | ↘ Probably worse | Retain claude-3-7-sonnet |
| Planner | claude-3-7-sonnet | ? Insufficient evidence | ? Insufficient evidence | Retain claude-3-7-sonnet |
| Reviewer | claude-3-7-sonnet | ? Insufficient evidence | ? Insufficient evidence | Retain claude-3-7-sonnet |
| Reasoner | o3-mini | ↘ Probably worse | ? Insufficient evidence | Retain o3-mini |
```

### 3. 周期性新模型监控（Continuous Monitor）

供外部 定时任务 调用的检测流程：

```bash
# 运行单次监控周期
./bin/model-watcher run

# 详细输出模式（即使无新模型也打印状态）
./bin/model-watcher run --verbose
```
- **首次运行（Bootstrap）**：将当前结构化来源中已有的数百个历史模型记录为基线 `SEEN`，**生成 0 份垃圾报告，不打扰用户**。
- **增量运行（Incremental）**：仅在权威数据源中发现真实新发布模型时触发评估，生成 `reports/` 报告并持久化状态至 `state.json`。

### 4. 查看当前校准与追踪状态

```bash
./bin/model-watcher status
```

---

## 📡 权威数据源层级规范

1. **P0 权威公开榜单**：
   - **LiveBench**（抗污染防泄露通用评测）
   - **SWE-bench Verified**（真实仓库级代码解决率）
   - **Harbor Hub**（Terminal-Bench 2.0 / 4.0 / 2.1 终端 Agent 评测）
2. **P1 独立标准化测试**：
   - **Artificial Analysis**（实时 API 吞吐、延迟、定价与官方发布日期）
   - **LMMs-Eval**（MMMU / MathVista 多模态评测）
3. **P2-P5 降级辅助**：
   - 厂商官方 Release Notes / Model Card
   - 严格禁止抓取未经证实的第三方自媒体新闻作为评测依据。

---

## 🛠️ 项目文件树

```
model-report/
├── SKILL.md                          # AI Agent Skill 技能定义文件
├── README.md                         # 英文官方文档
├── README_CN.md                      # 中文官方文档
├── README_AGENT.md                   # AI Agent (OpenClaw/Hermes) 自动化部署集成指南
├── profile.yaml.example              # 用户基线配置模板（含 revision 与 calibrated_at）
├── state.json.example                # 状态库结构范例
├── bin/
│   └── model-watcher                 # 纯 Shell 包装的快速启动入口
├── src/
│   └── model_watcher/
│       ├── cli.py                    # CLI 入口与指令调度
│       ├── config.py                 # Baseline Calibration 生命周期管理
│       ├── aggregator.py             # 权威来源候选聚合与证据链检索
│       ├── evaluator.py              # 7-Role 核心对比评估引擎
│       ├── reporter.py               # Markdown 报告与跨模型推荐渲染器
│       └── state.py                  # 轻量 JSON 状态持久化管理
└── tests/                            # 覆盖全套场景的单元与集成测试集
```

---

## 🧪 运行测试套件

```bash
uv run python3 -m unittest discover -s tests
```
