# DevBot 设计决策记录

> 记录项目设计过程中的关键讨论、权衡取舍和最终决策依据。
> 按主题分类，每条包含：问题 → 分析 → 结论。

---

## 1. 架构范式：为什么是 Harness + Agent 混合？

**问题**：代码审查 Agent 应该全自主（像通用 Agent 一样自由探索），还是全确定性（像传统 lint 工具）？

**分析**：
- 全自主：不可控，可能遗漏文件、死循环、成本爆炸
- 全确定性：无法处理需要"理解语义"的复杂 bug

**结论**：混合范式——
- **Harness（确定性）** 管"必须做到的事"：文件筛选、分组、Critic 启动数量、行号校验、结论复核
- **Agent（自主）** 管"怎么做好"：上下文获取、工具调用、问题识别、建议生成

**面试话术**：
> "确定性 Harness 保证流程可靠性，Agent 自主性保证审查深度。两者职责不重叠。"

---

## 2. 为什么移除 codedoc / 不做 RAG？

**问题**：原简历方案依赖 codedoc 代码知识图谱，移除后用什么替代？要不要做 RAG 知识库？

**分析**：
- RAG 需要预先 embedding 整个仓库 → 维护成本高、更新延迟
- 代码审查是"精确定位"场景（谁调用了这个函数），不是"模糊语义"场景
- grep + read_file 精确且零延迟，比向量检索更适合

**结论**：零预取 + 3 个文本级工具，Critic 按需自主获取上下文。

**RAG 唯一有价值的场景**：团队隐性规范召回（历史 MR 评论中沉淀的共识），但需要大量历史数据，MVP 不做。

**面试话术**：
> "我评估过 RAG，结论是核心流程不需要。代码审查是精确定位场景，grep 比语义搜索更可靠。不做 RAG 不是能力不足，是技术判断。"

---

## 3. 工具层：为什么只有 3 个工具？

**最终工具集**：
| 工具 | 作用域 | 用途 |
|---|---|---|
| `read_file(path, start?, end?)` | 整个仓库 | 读取完整代码 |
| `grep(pattern, path?, glob?)` | 整个仓库 | 正则搜索定位 |
| `get_diff_file(path)` | 仅 MR 变更文件 | 查看变更内容 |

### 3.1 为什么不要 Tree-sitter AST 工具？

**分析**：
- grep 能找到函数定义（`def function_name`）和调用（`function_name(`）
- AST 解析增加复杂度（多语言 grammar 维护），收益有限
- 阿里 OCR 生产验证：4 个文本级工具足够覆盖审查需求

**结论**：grep 是 AST 工具的上位替代（更通用、更简单）。

### 3.2 为什么不要 list_dir / glob？

**分析**：
- Critic 的起点是 diff（已知文件路径），不需要"发现"文件
- 想找调用方 → grep("function_name") 直接定位
- list_dir 容易导致 Agent 漫无目的探索（"先看看目录结构"→ 浪费 token）

**结论**：Critic 是目标驱动的（从 diff 出发），不需要目录浏览能力。

### 3.3 工具作用域差异（影响面分析）

```
get_diff_file → 只能查 MR 中变更的文件
read_file     → 能读整个仓库任何文件（clone 下来的）
grep          → 能搜整个仓库任何文件
```

**关键**：修改了函数 A，即使调用方 B 不在本次 MR 中，Critic 也能通过 grep 找到 B 并 read_file 审查影响。

---

## 4. Bundle 机制：为什么打包而不是单文件处理？

**问题**：file_grouper 把多个文件打成一个 bundle，为什么不直接单文件处理？

**分析**：

| | 单文件 | Bundle |
|---|---|---|
| 10 文件 × 4 Critic | 40 次 LLM 调用 | 3 bundle × 4 = 12 次 |
| 固定 token 开销 | 40 × 1500 = 60,000 | 12 × 1500 = 18,000 |

**结论**：Bundle 的核心价值是**成本优化**（减少重复的 system prompt / 工具 schema / 规则注入开销）。

**补充**：
- "同 bundle 内 diff 互相可见"只是锦上添花，不是核心收益
- 跨文件关联审查不依赖 bundle 分组，而是依赖工具层（grep + read_file + get_diff_file）
- 文件是最小单位不可拆分，超 800 行独占一个 bundle

---

## 5. Bundle 内容是 diff 文本，不是完整文件

**澄清**：Bundle 放进 Critic prompt 的是各文件的 **diff 片段**（变更行），不是完整源码。

```
Critic 能直接看到的：各文件的改动行（+/- 行）
Critic 看不到的：未改动的代码、完整函数体
```

所以即使同 bundle，Critic 想深入了解某个函数的完整实现，仍然需要调 `read_file`。

---

## 6. 跨 Bundle 关联审查怎么做？

**问题**：分了 3 个 bundle，bundle 之间有代码依赖怎么办？

**机制**：
1. 每个 Critic 输入中附带**本次 MR 全量变更文件路径清单**（仅路径，不含内容）
2. Critic 审查当前 bundle 时，如果怀疑关联其他文件 → 主动调 `get_diff_file(path)` 获取
3. 如果关联的是未变更文件 → 调 `grep` + `read_file`

**关键**：这是 Agent 自主决策（"怎么做好"），不是 Harness 强制的。

---

## 7. 4 个 Critic 的设计

### 7.1 为什么是 4 个？

| Critic | 视角 | 关注点 |
|---|---|---|
| correctness | 逻辑正确性 | 空指针、边界、竞态、类型错误 |
| security | 安全性 | 注入、越权、敏感信息泄露 |
| performance | 性能 | N+1 查询、内存泄漏、不必要循环 |
| quality | 工程质量 | 命名、重复代码、缺少错误处理 |

### 7.2 Critic 间零通信

- 4 个 Critic 完全并行、互不知晓对方存在
- 由 Aggregator 统一聚合去重
- 好处：无通信开销、无顺序依赖、单个失败不影响其他

### 7.3 Critic 是 ReAct Agent，但不嵌套 sub-agent

每个 Critic 本身是一个 ReAct 循环（思考 → 调工具 → 观察 → 再思考），但内部不再嵌套子 Agent：
- 嵌套增加延迟和复杂度
- 单 Critic 的工具调用轮次 ≤ 8，足够完成审查
- 并行加速已由 4 Critic 并发实现

---

## 8. 多层兜底机制

### 质量兜底（防误报）— 5 层漏斗

```
① Prompt 领域纪律 → 源头控制（"不确定就给低 confidence"）
② Confidence < 0.4 → Aggregator 直接丢弃
③ 跨 Critic 去重 → 同位置多报合并
④ Reflector 验证 → 行号校验（确定性）+ 逻辑验证（LLM）
⑤ Risk score < 70 → 只评论不阻断
```

### 工程兜底（防崩溃）

| 故障 | 机制 |
|---|---|
| LLM API 超时 | 重试 + httpx timeout |
| 输出格式错误 | Structured Output 强制 JSON schema |
| 单 Critic 失败 | 其他 3 个降级运行 |
| 工具调用死循环 | max_iterations=8 硬限 |
| git clone 失败 | 设 Commit Status = error |
| 全流程超时 | asyncio 全局 5 分钟超时 |

---

## 9. 为什么不跑两遍完整流程再合并？

**问题**：能不能 asyncio.create_task 跑两遍审查，然后合并去重？

**分析**：
- 同样的 prompt + 同样的 diff → 大概率产出相同 findings
- 成本翻倍，收益极小（仅减少随机遗漏）
- 我们已经有 4 个**异质** Critic（不同视角），这比"同质重复"有价值得多

**结论**：
- 并行已在做（4 Critic 并发）
- 去重校验已在做（Aggregator + Reflector）
- 真正有价值的"第二遍"是 Reflector 做**判别**（验证问题是否成立），不是重复**生成**

---

## 10. rule_matcher 的规则源

**当前**：硬编码 Python dict（MVP 跑通用）

**生产应该是**：
```
rules/
├── python.yaml          ← 团队编码规范
├── security.yaml        ← 安全红线
└── team-conventions.yaml ← 团队约定
```

**核心价值不在规则内容，而在"确定性注入"机制**——工程逻辑决定注入什么规则，不是让 LLM 自由发挥。规则内容是可替换的数据源。

---

## 11. 与阿里 Open Code Review (OCR) 的对比

| 维度 | 阿里 OCR | 我们 (DevBot) |
|---|---|---|
| 编排 | 自研 pipeline（Node.js） | LangGraph Send API |
| 分解轴 | 按文件分治（sub-agent per file） | 按视角分治（Critic per perspective） |
| 工具 | 4 个文本级工具 | 3 个（去掉 list_dir） |
| 上下文 | 零预取 + 工具按需获取 | 相同 |
| 规则 | 内部模板库 | rule_matcher + YAML |
| 验证 | 定位 + 反思 | Reflector（行号 + 逻辑） |
| 模型 | 内部模型 | Qwen（DashScope） |
| 平台 | 内部 Git | GitLab |

**核心差异**：分解轴不同。他们按文件切（每个 sub-agent 看一个文件的所有问题），我们按视角切（每个 Critic 看所有文件的一类问题）。

---

## 12. 技术选型决策

| 选型 | 决策 | 理由 |
|---|---|---|
| LLM | Qwen（qwen-plus / qwen-max） | DashScope API，兼容 OpenAI SDK |
| 平台 | GitLab | Webhook + Discussion API |
| 编排 | LangGraph | Send API 天然支持并行扇出 |
| 框架 | FastAPI | 异步、轻量、Webhook 接入 |
| 配置 | pydantic-settings | 环境变量注入，类型安全 |
| 校准 | scikit-learn Platt | 风险分量化闭环 |

---

## 13. 零预取原则

**定义**：不在 Critic 启动前预先加载任何代码上下文（不用 Tree-sitter 解析、不用 RAG 检索、不预先读文件）。

**理由**：
- 预取可能取错（浪费 token）
- Agent 通过工具按需获取更精准
- 减少系统复杂度（无需维护索引）

**唯一例外**：diff 文本本身是"预取"的（由 Harness 解析好放进 prompt），因为这是审查的起点，100% 必要。

---

*最后更新：2026-07-28*
