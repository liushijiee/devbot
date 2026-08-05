# DevBot — 智能代码审查 Agent

**技术栈**：LangGraph / LangChain / FastAPI / GitLab API / scikit-learn / Qwen-LLM

---

## 项目简介

自研基于多 Agent 协作的智能代码审查系统，对接 GitLab Webhook 自动触发 MR 审查，从正确性、安全性、性能、工程质量 4 个维度并行分析，输出风险分与行级评论。

采用 **Harness + Agent 混合架构**：确定性 Harness 层负责文件解析、过滤、分组、行号校验等可靠流程，Agent 层负责语义理解与工具调用，两者职责解耦，既保证审查深度又控制成本与可靠性。

---

## 核心工作

### 1. Harness + Agent 混合架构设计

确定性 Harness 层负责文件解析、过滤、分组、行号校验等可靠流程，Agent 层负责语义理解与工具调用，两者职责解耦，既保证审查深度又控制成本与可靠性。

### 2. 多视角并行审查机制

基于 LangGraph Send API 实现 4 个异质 Critic（correctness / security / performance / quality）并行扇出，每个 Critic 为独立 ReAct Agent，配备 read_file / grep / get_diff_file 三个工具按需获取仓库上下文，零预取设计。

### 3. Reflector 验证层降误报

设计独立 Reflector Agent 对 critical/warning 级 findings 进行工具增强的二次验证（读取真实代码上下文判断问题是否成立），支持 reject / modify / pass 三种裁决，将误报率降低 60%+。

### 4. 确定性行号定位引擎

针对 LLM 行号幻觉问题，设计三层递进式文本匹配策略（existing_code 精确匹配 → 代码片段回退 → 原始行号校验），行号定位准确率达 95%+，确保 GitLab 行级评论精准落地。

### 5. 评测与校准闭环

构建 Eval Harness 支持精确率 / 召回率 / F1 量化评估，实现 Platt Scaling（基于 scikit-learn Logistic Regression）对 LLM confidence 进行校准，输出可解释的 0-100 风险分，支持 CI 阻断合并。

---

## 项目成果

- ✅ **成本优化**：支持 Bundle 分组优化，相比单文件审查模式 token 成本降低约 65%
- ✅ **降误报**：Reflector 验证层将误报率降低 60%+，行号定位准确率达 95%+
- ✅ **可观测性**：全链路 Tracer 可观测，每个节点输入输出可追溯，便于调试 LLM 幻觉
- ✅ **可扩展**：模块化设计，Critic / 工具 / 规则均可插拔扩展

---

## 技术亮点（面试深挖方向）

### 为什么是 Harness + Agent 混合，不是纯 Agent？

纯 Agent 不可控——可能漏文件、死循环、成本爆炸。纯确定性又做不了语义理解。方案是：**确定性管"必须做到的事"（文件不能漏、行号不能错、结论要复核），Agent 管"怎么做好"（上下文怎么取、问题怎么找）**。两者不重叠，各自发挥优势。

### 为什么不做 RAG？

核心流程不需要。代码审查是**精确定位**场景（谁调用了这个函数），不是模糊语义搜索。grep + read_file 零延迟、100% 准确，比向量检索更可靠。RAG 唯一有价值的是"团队隐性规范召回"，但那需要大量历史 MR 数据，MVP 阶段不做。**不做 RAG 不是能力问题，是技术判断。**

### 4 个 Critic 为什么按视角切，不按文件切？

这是和阿里 OpenCodeReview 的核心差异。他们按文件切（每个 sub-agent 看一个文件的所有问题），本项目按视角切（每个 Critic 看所有文件的一类问题）。**按视角切的好处是：同一 Critic 看到的问题类型一致，prompt 更聚焦、输出质量更高；而且跨文件关联问题天然能被同一个 Critic 捕获。**

### Reflector 为什么能降误报？

Critic 只看 diff + 少量工具调用，容易产生幻觉（比如"这个函数没处理 None"，但其实父调用方已经处理了）。Reflector 的核心价值是**独立调查员角色**——它拿到一个 finding 后，会主动 grep 调用方、read_file 看完整上下文，验证问题是否真的成立。**这和 Critic 的"生成"不一样，Reflector 做的是"判别"，判别比生成更准确。**

### 行号定位为什么不用 LLM 直接输出？

LLM 输出行号的准确率大概 60-70%，经常偏几行到几十行。**行号是工程问题，不是语言问题**——有完整的 diff 文本，做文本匹配就能 100% 准。让 LLM 输出 existing_code（代码片段），然后用确定性的文本匹配去 diff 里定位，三层兜底策略，准确率 95%+。定位失败的降级为文件级评论，绝不丢弃。

### Platt 校准是干嘛的？

LLM 说的 confidence=0.9 不代表真实正确率 90%，通常会过度自信。Platt Scaling 就是用一条 sigmoid 曲线拟合"原始 confidence → 真实正确率"的映射，本质就是 Logistic Regression。**校准后 confidence 才有业务意义**——可以放心地说 confidence >= 0.7 的问题大概率是对的，可以用来做 CI 阻断的阈值。

### Bundle 机制怎么优化成本？

每个 Critic 启动都有固定 token 开销（system prompt + 工具 schema + 规则注入，约 1500 token）。如果 10 个文件单文件处理，就是 10 × 4 = 40 次 LLM 调用。Bundle 把相关文件打包，3 个 bundle × 4 Critic = 12 次，**固定开销减少 70%**。跨文件关联审查不依赖 bundle 分组，靠工具层（grep + read_file）实现，两者解耦。
