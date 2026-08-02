# run_review 完整流程（基于 log.js 真实数据）

## 第0步：run_review 入口

```python
async def run_review(
    changes: list[dict],
    repo_url: str,
    branch: str,
    mr_iid: int = 0,
    project_id: int = 0,
) -> dict:
```

**输入**（来自 `initial_state`）：

```python
changes    = gitDiffRes  # 14 个文件的 diff JSON
repo_url   = "https://oauth2:***@jihulab.com/liushijie_2000-group/devbot.git"
branch     = "master"
mr_iid     = 5
project_id = 356482
```

---

## 第1步：Clone 仓库

```python
repo_manager = RepoManager()
await repo_manager.clone(repo_url, branch)
```

| | 值 |
|---|---|
| **输入** | `repo_url`, `branch="master"` |
| **输出** | `clone_path = Path("/tmp/devbot_repos/xxxxx/")` ← 本地临时目录 |

---

## 第2步：parse_gitlab_changes

```python
file_changes = parse_gitlab_changes(changes)
```

| | 值 |
|---|---|
| **输入** | `changes`（14 个 dict，即 log.js 中的 `gitDiffRes`） |
| **输出** | 14 个 `FileChange` 对象 |

```python
# 14 个 FileChange 对象（含完整 hunks、diff_text、标志位）
# 每个 FileChange 包含: path, language, hunks, is_new, is_deleted, is_renamed, changed_lines, diff_text

[
    FileChange(
        path='app/gitlab/client.py',
        language='python',
        hunks=[
            Hunk(old_start=1, old_lines=4, new_start=1, new_lines=12,
                 content='@@ -1,4 +1,12 @@\n+"""\n+GitLab API 客户端\n+封装 MR 评论、Commit Status、获取 diff 等操作。\n+...\n+"""\n...'),
            Hunk(old_start=43, old_lines=6, new_start=51, new_lines=10,
                 content='@@ -43,6 +51,10 @@ class GitLabClient:\n+        if not new_line or new_line < 1:\n+            logger.warning(...)...'),
            Hunk(old_start=51, old_lines=6, new_start=63, new_lines=7,
                 content='@@ -51,6 +63,7 @@ class GitLabClient:\n+                "old_path": new_path,...'),
        ],
        is_new=False, is_deleted=False, is_renamed=False,
        changed_lines=13,
        diff_text='@@ -1,4 +1,12 @@\n+"""\n+GitLab API 客户端...\n@@ -43,6 +51,10 @@...\n@@ -51,6 +63,7 @@...',
    ),

    FileChange(
        path='app/gitlab/webhook.py',
        language='python',
        hunks=[
            Hunk(old_start=1, old_lines=4, new_start=1, new_lines=17,
                 content='@@ -1,4 +1,17 @@\n+"""\n+GitLab Webhook 路由\n+接收 MR 事件，X-Gitlab-Token 校验...\n+"""\n...'),
            Hunk(old_start=68, old_lines=7, new_start=81, new_lines=7,
                 content='@@ -68,7 +81,7 @@\n-    logger.debug(f"[\u5ba1\u67e5] repo_url: {repo_url[:50]}...")\n+    logger.debug(f"[\u5ba1\u67e5] repo_url: {repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:50]}...")'),
        ],
        is_new=False, is_deleted=False, is_renamed=False,
        changed_lines=17,
        diff_text='@@ -1,4 +1,17 @@\n+"""\n+GitLab Webhook 路由...\n@@ -68,7 +81,7 @@...',
    ),

    FileChange(
        path='app/graph/builder.py',
        language='python',
        hunks=[
            Hunk(old_start=1, old_lines=4, new_start=1, new_lines=15,
                 content='@@ -1,4 +1,15 @@\n+"""\n+LangGraph 图构建器\n+...\n+"""\n...'),
            Hunk(old_start=160, old_lines=7, new_start=171, new_lines=8,
                 content='@@ -160,7 +171,8 @@\n-        logger.info(f"[RunReview] \u5f00\u59cb clone \u4ed3\u5e93: {repo_url[:60]}... branch={branch}")\n+        safe_url = repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:60]\n+        logger.info(f"[RunReview] \u5f00\u59cb clone \u4ed3\u5e93: {safe_url} | branch={branch}")'),
        ],
        is_new=False, is_deleted=False, is_renamed=False,
        changed_lines=14,
        diff_text='...',
    ),

    FileChange(path='app/graph/nodes.py',         language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=12),
    FileChange(path='app/graph/state.py',         language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=10),
    FileChange(path='app/harness/diff_parser.py', language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=42),
    FileChange(path='app/harness/file_filter.py', language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=27),
    FileChange(path='app/harness/file_grouper.py',language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=27),

    FileChange(
        path='app/harness/repo_manager.py',
        language='python',
        hunks=[
            Hunk(old_start=1, old_lines=7, new_start=1, new_lines=26,
                 content='@@ -1,7 +1,26 @@\n+"""\n+1\u4ed3\u5e93\u7ba1\u7406\u5668\n+...\n+"""\n...'),
            Hunk(old_start=33, old_lines=6, new_start=52, new_lines=8,
                 content='@@ -33,6 +52,8 @@ class RepoManager:\n+        # mkdtemp \u4f1a\u521b\u5efa\u76ee\u5f55\uff0c\u4f46 git clone \u8981\u6c42\u76ee\u6807\u4e0d\u5b58\u5728\uff0c\u5148\u5220\u6389\n+        shutil.rmtree(self._clone_path)...'),
            Hunk(old_start=45, old_lines=16, new_start=66, new_lines=18,
                 content='@@ -45,16 +66,18 @@ class RepoManager:\n-        process = await asyncio.create_subprocess_exec(...)\n+        # Windows \u4e0a asyncio.create_subprocess_exec \u4e0d\u517c\u5bb9 uvicorn \u4e8b\u4ef6\u5faa\u73af\n+        loop = asyncio.get_event_loop()\n+        result = await loop.run_in_executor(...)\n...'),
        ],
        is_new=False, is_deleted=False, is_renamed=False,
        changed_lines=39,
        diff_text='...',
    ),

    FileChange(path='app/harness/rule_matcher.py',language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=24),
    FileChange(path='app/prompts/registry.py',    language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=11),
    FileChange(path='app/tools/code_tools.py',    language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=13),
    FileChange(path='app/config.py',              language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=6),
    FileChange(path='app/main.py',                language='python', hunks=[1个Hunk], is_new=False, is_deleted=False, is_renamed=False, changed_lines=4),
]
```

> 以上数据与 log.js 中 `parse_gitlab_changes` 变量完全一致。前 3 个文件和 `repo_manager.py` 展示了完整的 hunks 详情（多个 Hunk 的情况），其余文件因都是单 Hunk 所以简写。

---

## 第3步：build_review_graph + graph.ainvoke

```python
graph = build_review_graph(repo_manager, file_changes)
result = await graph.ainvoke(initial_state)
```

`initial_state` 传入图时：

```python
{
    "changes": gitDiffRes,       # 14 个文件 JSON
    "repo_url": "https://...",
    "branch": "master",
    "mr_iid": 5,
    "project_id": 356482,
    # diff_text, changed_files, rules 等字段还没填，由 prepare 填充
}
```

---

## 第4步：prepare 节点

```python
def prepare(state: ReviewState) -> dict:
```

**输入**: `state`（含 `changes` 字段）

内部依次调用 3 个子函数：

### 4a. parse_gitlab_changes（内部再调一次）

| | 值 |
|---|---|
| **输入** | `state["changes"]`（14 个 dict） |
| **输出** | 14 个 `FileChange`（同第2步输出，含 hunks、diff_text 等完整字段） |

### 4b. filter_files

| | 值 |
|---|---|
| **输入** | 14 个 `FileChange` |
| **输出** | **14 个全部保留**，0 个被过滤 |

> 全部是 `.py` 文件，没有 lock 文件、图片、`__pycache__`、deleted 文件，不命中任何 `EXCLUDE_PATTERNS`。

### 4c. group_files（阈值 800 行）

按 `changed_lines` 降序排列后贪心打包：

```
排序后:
  diff_parser(42), repo_manager(39), file_filter(27), file_grouper(27),
  rule_matcher(24), webhook(17), builder(14), client(13), code_tools(13),
  nodes(12), registry(11), state(10), config(6), main(4)

总计: 42+39+27+27+24+17+14+13+13+12+11+10+6+4 = 259 行 < 800
```

| | 值 |
|---|---|
| **输入** | 14 个 `FileChange`，`max_lines=800` |
| **输出** | **1 个 Bundle**（259行，全部打包在一起） |

> 因为只有一个 bundle，所以 `bundle = bundles[0]` 在这个 MR 中不会丢失文件。

### 4d. match_rules

| | 值 |
|---|---|
| **输入** | Bundle 内的 14 个文件（全是 `language="python"`） |
| **输出** | 6 条匹配规则 |

匹配过程：
- **语言规则**：`python` → 4 条（类型注解、异常处理、资源管理、可变默认参数）
- **路径规则**：`app/config.py` 命中 `r".*/config.*|.*setting.*|.*\.env.*"` → 2 条（敏感信息硬编码、配置默认值）

输出的 `rules` 文本：

```
【本次审查需重点关注的规则】
  - 检查是否缺少类型注解（函数参数和返回值）
  - 检查异常处理：是否有裸 except、是否吞掉了异常
  - 检查资源管理：文件/连接是否使用 with 语句
  - 检查可变默认参数（如 def f(items=[])）
  - 检查是否有敏感信息硬编码
  - 检查配置项是否有默认值
```

### prepare 最终输出

`diff_text`（Bundle 内所有文件的 diff 拼接，以 `app/gitlab/client.py` 和 `app/gitlab/webhook.py` 为例）：

```
--- app/gitlab/client.py ---
@@ -1,4 +1,12 @@
+"""
+GitLab API 客户端
+封装 MR 评论、Commit Status、获取 diff 等操作。
...
@@ -43,6 +51,10 @@ class GitLabClient:
+        if not new_line or new_line < 1:
+            logger.warning(f"[GitLab] 行号无效({new_line})，跳过行级评论: {new_path}")
+            return
...

--- app/gitlab/webhook.py ---
@@ -1,4 +1,17 @@
+"""
+GitLab Webhook 路由
+接收 MR 事件，X-Gitlab-Token 校验，异步触发评审。
...

...(共 14 个文件的 diff 全部拼接)
```

`changed_files`：

```
- app/gitlab/client.py
- app/gitlab/webhook.py
- app/graph/builder.py
- app/graph/nodes.py
- app/graph/state.py
- app/harness/diff_parser.py
- app/harness/file_filter.py
- app/harness/file_grouper.py
- app/harness/repo_manager.py
- app/harness/rule_matcher.py
- app/prompts/registry.py
- app/tools/code_tools.py
- app/config.py
- app/main.py
```

`rules`（完整文本）：

```
【本次审查需重点关注的规则】
  - 检查是否缺少类型注解（函数参数和返回值）
  - 检查异常处理：是否有裸 except、是否吞掉了异常
  - 检查是否有敏感信息硬编码
  - 检查可变默认参数（如 def f(items=[])）
  - 检查资源管理：文件/连接是否使用 with 语句
  - 检查配置项是否有默认值
```

`all_file_paths`：

```python
[
    "app/gitlab/client.py",
    "app/gitlab/webhook.py",
    "app/graph/builder.py",
    "app/graph/nodes.py",
    "app/graph/state.py",
    "app/harness/diff_parser.py",
    "app/harness/file_filter.py",
    "app/harness/file_grouper.py",
    "app/harness/repo_manager.py",
    "app/harness/rule_matcher.py",
    "app/prompts/registry.py",
    "app/tools/code_tools.py",
    "app/config.py",
    "app/main.py",
]
```

---

## 第5步：route_to_critics（条件边）

```python
def route_to_critics(state: ReviewState) -> list[Send]:
```

| | 值 |
|---|---|
| **输入** | prepare 产出的 state（`diff_text` 非空） |
| **输出** | 4 个 `Send`，每个携带完整 state + 自己的 `critic_name` |

```python
# CRITIC_NAMES = ["correctness", "security", "performance", "quality"]
return [
    Send("critic_node", {"critic_name": "correctness", **state}),
    Send("critic_node", {"critic_name": "security",    **state}),
    Send("critic_node", {"critic_name": "performance", **state}),
    Send("critic_node", {"critic_name": "quality",     **state}),
]
```

---

## 第6步：critic_node × 4（并行执行）

以 **security** critic 为例（其他 3 个同理）：

### critic_node 输入

```python
state = {
    "critic_name": "security",
    "diff_text": "--- app/gitlab/client.py ---\n@@ -1,4 +1,12 @@\n+\"\"\"GitLab API 客户端...\n...(14个文件完整diff)",
    "changed_files": "- app/gitlab/client.py\n- app/gitlab/webhook.py\n- ...\n- app/main.py",
    "rules": "【本次审查需重点关注的规则】\n  - 检查是否缺少类型注解...\n  - 检查异常处理...\n  - ...",
    "changes": gitDiffRes,
    "repo_url": "https://oauth2:***@jihulab.com/...",
    "branch": "master",
    "mr_iid": 5,
    "project_id": 356482,
    "all_file_paths": ["app/gitlab/client.py", ..., "app/main.py"],
}
```

### 6a. load_prompt("security")

加载 `security.yaml` 模板，获取 `system_prompt` 和 `user_prompt` 模板。

### 6b. template.format_user(...)

用 `changed_files`、`diff_text`、`rules` 填充模板，生成 `user_prompt`（以 security.yaml 为例）：

```
请审查以下代码变更中的安全问题：

变更文件：
- app/gitlab/client.py
- app/gitlab/webhook.py
- app/graph/builder.py
- app/graph/nodes.py
- app/graph/state.py
- app/harness/diff_parser.py
- app/harness/file_filter.py
- app/harness/file_grouper.py
- app/harness/repo_manager.py
- app/harness/rule_matcher.py
- app/prompts/registry.py
- app/tools/code_tools.py
- app/config.py
- app/main.py

代码 diff：
--- app/gitlab/client.py ---
@@ -1,4 +1,12 @@
+"""GitLab API 客户端...
...(14个文件完整 diff)

审查规则：
【本次审查需重点关注的规则】
  - 检查是否缺少类型注解（函数参数和返回值）
  - 检查异常处理：是否有裸 except、是否吞掉了异常
  - 检查是否有敏感信息硬编码
  - 检查可变默认参数（如 def f(items=[])）
  - 检查资源管理：文件/连接是否使用 with 语句
  - 检查配置项是否有默认值

你可以使用工具 read_file、grep、get_diff_file 来深入了解代码上下文。
请以 JSON 数组格式输出你的发现。
```

### 6c. create_tools(repo_manager, file_changes)

创建 3 个工具供 Agent 调用：
- `read_file(path)` — 读取 clone 下来的仓库文件
- `grep(pattern, path)` — 正则搜索代码
- `get_diff_file(file_path)` — 获取指定文件的 diff

### 6d. ReAct Agent 执行

```python
agent = create_react_agent(model=llm, tools=tools, prompt=SystemMessage(system_prompt))
result = await agent.ainvoke(
    {"messages": [HumanMessage(user_prompt)]},
    config={"recursion_limit": 21},  # max_tool_rounds(8) * 2 + 5
)
```

Agent 内部多轮对话示例（模拟）：

| 步骤 | 类型 | 内容 |
|---|---|---|
| 1 | LLM 思考 | "让我看看 repo_manager.py 的改动" |
| 2 | Tool Call | `read_file("app/harness/repo_manager.py")` |
| 3 | Tool Result | 文件完整内容 |
| 4 | LLM 思考 | "再看看 client.py 的改动" |
| 5 | Tool Call | `get_diff_file("app/gitlab/client.py")` |
| 6 | Tool Result | diff 文本 |
| 7 | LLM 最终回复 | JSON 数组（findings） |

### 6e. _parse_findings 解析

**输入** (`text`): Agent 最后一条 AI 消息的内容：

```
经过审查，我发现了以下问题：

[
    {
        "file": "app/harness/repo_manager.py",
        "line": 52,
        "severity": "warning",
        "title": "shutil.rmtree 删除临时目录可能有竞态条件",
        "description": "mkdtemp 创建目录后立即 rmtree，如果目录被其他进程使用可能出问题",
        "suggestion": "考虑使用 ignore_errors=True",
        "confidence": 0.7
    },
    {
        "file": "app/gitlab/client.py",
        "line": 63,
        "severity": "info",
        "title": "position 对象新增 old_path 字段",
        "description": "新增 old_path 确保 GitLab Discussion API 正确定位行",
        "suggestion": "无需修改，仅为记录此改进",
        "confidence": 0.6
    }
]
```

**输出**: 每个 finding 被打上 `critic` 标签：

```python
[
    {
        "file": "app/harness/repo_manager.py",
        "line": 52,
        "severity": "warning",
        "title": "shutil.rmtree 删除临时目录可能有竞态条件",
        "description": "mkdtemp 创建目录后立即 rmtree...",
        "suggestion": "考虑使用 ignore_errors=True",
        "confidence": 0.7,
        "critic": "security",     # ← _parse_findings 加上的
    },
    {
        "file": "app/gitlab/client.py",
        "line": 63,
        "severity": "info",
        "title": "position 对象新增 old_path 字段",
        "description": "...",
        "suggestion": "无需修改，仅为记录此改进",
        "confidence": 0.6,
        "critic": "security",
    },
]
```

### 6f. critic_node 输出

```python
{"critic_results": [{
    "critic_name": "security",
    "findings": [上述2个finding],
    "error": None,
}]}
```

4 个 critic 并行执行后，通过 `operator.add` reducer 自动合并到 `state["critic_results"]`：

```python
[
    {"critic_name": "correctness", "findings": [3个], "error": None},
    {"critic_name": "security",    "findings": [2个], "error": None},
    {"critic_name": "performance", "findings": [1个], "error": None},
    {"critic_name": "quality",     "findings": [2个], "error": None},
]
```

---

## 第7步：aggregate 节点

```python
def aggregate(state: ReviewState) -> dict:
```

| | 值 |
|---|---|
| **输入** | `state["critic_results"]`（4 个 CriticResult，共约 8 个 findings） |
| **输出** | `state["aggregated_findings"]`（去重排序后的 findings 列表） |

处理过程：

1. **合并**: 8 个 findings 放到一个列表
2. **confidence 过滤**: 保留 `confidence >= 0.4` 的
3. **去重**: 同 file + line + severity 只保留 confidence 最高的
4. **排序**: critical → warning → info

```python
{
    "aggregated_findings": [
        {"severity": "warning", "file": "app/harness/repo_manager.py", "line": 52,
         "confidence": 0.7, "critic": "security", ...},
        {"severity": "warning", "file": "app/gitlab/client.py", "line": 51,
         "confidence": 0.65, "critic": "correctness", ...},
        {"severity": "info",    "file": "app/graph/builder.py", "line": 106,
         "confidence": 0.55, "critic": "quality", ...},
        # ... 假设最终 5-6 个
    ]
}
```

---

## 第8步：reflect 节点

```python
async def reflect(state: ReviewState) -> dict:
```

| | 值 |
|---|---|
| **输入** | `state["aggregated_findings"]` + `state["diff_text"]` |
| **输出** | `state["verified_findings"]`（验证后的 findings） |

对每个 finding 逐个验证：

| finding | severity | 处理方式 |
|---|---|---|
| repo_manager.py:52 warning | warning | 调 LLM → `{"verdict": "pass"}` → 原样保留 |
| client.py:51 warning | warning | 调 LLM → `{"verdict": "modify", "modified_finding": {...}}` → 替换为修正版 |
| builder.py:106 info | info | **直接通过**（不调 LLM，节省 token） |

> **注意**: modify 时的修正版 finding 是由 Reflector LLM 自身生成的，不是回传给 Critic 重新分析。

```python
{
    "verified_findings": [
        # pass 的保留原样
        {"severity": "warning", "file": "app/harness/repo_manager.py", "line": 52, ...},
        # modify 的已被替换为 Reflector 给出的修正版
        {"severity": "warning", "file": "app/gitlab/client.py", "line": 54, "title": "修正后的标题", ...},
        # info 的直接通过
        {"severity": "info", "file": "app/graph/builder.py", "line": 106, ...},
        # 假设最终 4-5 个（有被 reject 丢弃的）
    ]
}
```

---

## 第9步：report 节点

```python
def report(state: ReviewState) -> dict:
```

| | 值 |
|---|---|
| **输入** | `state["verified_findings"]`（最终 4-5 个 findings） |
| **输出** | `state["risk_score"]` + `state["summary"]` + `state["comments"]` |

### 风险分计算

```python
# 假设 2 个 warning + 2 个 info
# warning: +15分/个, info: +5分/个
risk_score = 2×15 + 2×5 = 40
```

### 摘要生成

```
## 🔍 DevBot 代码审查报告

**风险分: 40/100**

| 级别 | 数量 |
|------|------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🔵 Info | 2 |

✅ 整体风险可控，建议处理后合并。
```

### 评论列表

每个 finding 生成一条 GitLab 行级评论：

```python
{
    "file": "app/harness/repo_manager.py",
    "line": 52,
    "body": "**[WARNING]** shutil.rmtree 删除临时目录可能有竞态条件\n\n...\n\n---\n*by DevBot (security critic) | confidence: 0.70*",
}
```

---

## 第10步：run_review 返回 + 清理

```python
result = await graph.ainvoke(initial_state)
# result 就是最终的 state，包含 risk_score, summary, comments
return result

# finally:
repo_manager.cleanup()  # 删除 /tmp/devbot_repos/xxxxx/
```

---

## 全流程总览

```
run_review(changes, repo_url, branch, mr_iid=5, project_id=356482)
│
├─ clone 仓库 → /tmp/devbot_repos/xxxxx/
├─ parse_gitlab_changes → 14 个 FileChange
├─ graph.ainvoke(initial_state)
│   │
│   ├─ prepare
│   │   ├─ filter_files: 14 → 14（全部保留）
│   │   ├─ group_files:  14 → 1 Bundle（259行 < 800）
│   │   └─ match_rules:  4条语言规则 + 2条路径规则 = 6条
│   │
│   ├─ route_to_critics → 4 个 Send（并行）
│   │   ├─ correctness Agent → N findings
│   │   ├─ security Agent    → N findings
│   │   ├─ performance Agent → N findings
│   │   └─ quality Agent     → N findings
│   │
│   ├─ aggregate: 合并 → 过滤(conf≥0.4) → 去重 → 排序
│   │
│   ├─ reflect: warning/critical 逐个LLM验证，info直接通过
│   │
│   └─ report: risk_score + summary + comments[]
│
└─ cleanup 临时仓库
```
