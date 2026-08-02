# 面试加分项：你目前缺的关键能力

## A. 核心 Agent 能力

| 他有的 | 源码位置 | 你的现状 |
| --- | --- | --- |
| 内存压缩（60%/80% 双阈值 + 三区模型） | llmloop/compression.go (11KB) | 无，对话历史无限增长 |
| 主循环 token 预算控制 | llmloop/loop.go (18KB) | 无 |
| CommentWorkerPool（异步后处理：定位→反思→建议验证） | llmloop/pool.go (5KB) | 无，同步阻塞 |
| 三层定位（hunk 匹配→全文件扫描→LLM 重定位） | diff/relocation.go + diff/hunk.go | LLM 直接输出行号 |
| Review Filter Task（主循环后 LLM 过滤误报） | agent.go 中 executeReviewFilter | Reflector 是逐条验证，不是批量过滤 |
| Suggest Diff（生成可一键采纳的修复代码） | suggestdiff/diff.go | 只给文字建议 |
| Plan 阶段（大文件先规划再审查） | agent.go 中 executePlanPhase | 无 |
| 工具按阶段分配（plan_task 和 main_task 用不同工具集） | config/toolsconfig/tools.json | 所有 Critic 用同一套工具 |

## B. 工程基础设施

| 他有的 | 源码位置 | 你该做的最小版本 |
| --- | --- | --- |
| Telemetry 6 个文件 | internal/telemetry/ | 接 LangSmith 或自己写 JSON trace |
| Session 持久化 + Resume | internal/session/ (5 文件) | 用 SQLite/JSON 存审查记录 + sha256 幂等 |
| Git 并发限制器 | gitcmd/runner.go | asyncio.Semaphore 限制 clone 并发 |
| LLM 多供应商适配 | llm/providers.go + resolver.go | 至少支持 2 个模型切换 |
| Token 用量追踪 | llm/usage_resolver.go | 从 DashScope 响应里提取 usage 字段并累计 |
| 连接测试 | config/testconnection/ | 启动时检测 API Key 是否有效 |
| 文件白名单系统 | config/allowlist/ (JSON 配置) | 你的 file_filter.py 是硬编码 |

## C. 产品化 / 面试展示力

| 他有的 | 你的现状 | 面试影响 |
| --- | --- | --- |
| Dockerfile / Makefile | 无 | 面试官问“怎么部署”你答不上 |
| CI/CD 示例（5 个平台） | 无 | 说明你只在本地跑过 |
| WebUI Session Viewer | 无 | 没有可视化展示手段 |
| CLI 多命令（review/scan/session/config/viewer） | 只有 Webhook | 产品形态单一 |
| VS Code 插件 | 无 | 加分项，但不是必须 |
| GitHub Action | 无 | 说明你没真正集成过 |
| 成本预估（scan 模式先估算 token） | 无 | 面试问成本你答不出 |
| 跨平台二进制分发 | 无 | 不需要 |

## D. 测试 / 质量保障

| 他有的 | 你的现状 |
| --- | --- | --- |
| 每个模块都有 _test.go（实际有 20+ 测试文件） | 4 个脚本式测试文件 |
| internal/session/testing.go — 测试辅助工具 | 无 |
| internal/tool/stub.go — 工具层 mock | 无 |
| examples/gerrit_ci/post_review_test.py — 连示例都有测试 | 无 |
| GitHub Actions CI（ci.yml）自动跑测试 | 无 CI |

## 你不需要全做：优先级排序

他的项目是 20 人团队 × 2 年 × 数万用户的产物。你不需要复刻，但面试 Agent 岗位，以下这些必须有：

### P0：必须有

- Token 统计 + 成本数据（从 DashScope response 提取 usage，累计到审查结果里）
- 确定性行号定位（学他的 existing_code + hunk 匹配，别用 LLM 输出行号）
- 内存压缩 / 上下文管理（至少实现“超过 N 轮工具调用就截断早期消息”）
- 幂等 + Session 记录（sha256 指纹去重 + JSON 文件存审查历史）
- 可观测性（每次审查输出完整 trace：tool calls、token、耗时）

### P1：强烈建议

- Plan 阶段（大文件先让 LLM 规划审查策略，再执行）
- 并发控制 + 超时（Semaphore + asyncio.wait_for）
- Dockerfile + docker-compose（FastAPI + Redis）
- CI（GitHub Actions 跑 pytest）
- Suggest Diff（评论里附带修复代码建议，GitLab 支持 suggestion 格式）

### P2：锦上添花

- WebUI 查看审查历史（Flask/FastAPI 简单页面）
- 多模型切换（critic 用 qwen-plus，reflector 用 qwen-max）
- 文件白名单改成 JSON 配置
- 成本预估（审查前估算 token）
