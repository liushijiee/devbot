let gitDiffRes = [{
    'diff': '@@ -1,4 +1,12 @@\n+"""\n+GitLab API 客户端\n+封装 MR 评论、Commit Status、获取 diff 等操作。\n \n+GitLab API 特点（vs GitHub）：\n+- 项目用 ID 或 URL-encoded path 标识（如 group%2Fproject）\n+- 行级评论通过 Discussions API 实现\n+- Commit Status API 参数略有不同\n+"""\n \n import logging\n import httpx\n@@ -43,6 +51,10 @@ class GitLabClient:\n         创建行级评论（通过 Discussion API）。\n         GitLab 行级评论需要 position 对象，比 GitHub 复杂。\n         """\n+        if not new_line or new_line < 1:\n+            logger.warning(f"[GitLab] 行号无效({new_line})，跳过行级评论: {new_path}")\n+            return\n+\n         url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/discussions"\n         payload = {\n             "body": body,\n@@ -51,6 +63,7 @@ class GitLabClient:\n                 "head_sha": head_sha,\n                 "start_sha": start_sha,\n                 "position_type": "text",\n+                "old_path": new_path,\n                 "new_path": new_path,\n                 "new_line": new_line,\n             },\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/gitlab/client.py',
    'old_path': 'app/gitlab/client.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,4 +1,17 @@\n-\n+"""\n+GitLab Webhook 路由\n+接收 MR 事件，X-Gitlab-Token 校验，异步触发评审。\n+\n+完整流程：\n+  Webhook → 校验 → 过滤事件 → 异步触发 _run_review()\n+  _run_review():\n+    1. 获取 MR 详情（sha、branch、repo URL）\n+    2. 获取 MR diff（changes JSON）\n+    3. 设置 Commit Status = "running"\n+    4. 调用 LangGraph 审查图（run_review）\n+    5. 发布审查结果（摘要 + 行级评论）\n+    6. 设置 Commit Status = "success" / "failed"\n+"""\n import asyncio\n import logging\n \n@@ -68,7 +81,7 @@ async def _run_review(webhook_data: dict):\n \n     logger.info(f"[审查] ══ 开始 ══ Project #{project_id} MR !{mr_iid}")\n     logger.info(f"[审查] 分支: {source_branch} | head_sha: {head_sha[:12]}...")\n-    logger.debug(f"[审查] repo_url: {repo_url[:50]}...")\n+    logger.debug(f"[审查] repo_url: {repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:50]}...")\n \n     try:\n \n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/gitlab/webhook.py',
    'old_path': 'app/gitlab/webhook.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,4 +1,15 @@\n+"""\n+LangGraph 图构建器\n+将所有节点组装为完整的审查流水线。\n \n+图结构：\n+  prepare ──→ Send × 4 Critics（并行）──→ aggregate ──→ reflect ──→ report\n+\n+关键机制：\n+- Send API: 确定性扇出到 4 个 Critic（不是 LLM 决定启动几个，是工程逻辑决定）\n+- operator.add reducer: 并行 Critic 的结果自动合并到 critic_results 列表\n+- 异步执行: Critic 和 Reflector 是 async 节点（LLM 调用）\n+"""\n \n import logging\n from typing import Any\n@@ -160,7 +171,8 @@ async def run_review(\n \n     repo_manager = RepoManager()\n     try:\n-        logger.info(f"[RunReview] 开始 clone 仓库: {repo_url[:60]}... branch={branch}")\n+        safe_url = repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:60]\n+        logger.info(f"[RunReview] 开始 clone 仓库: {safe_url} | branch={branch}")\n         await repo_manager.clone(repo_url, branch)\n         logger.info(f"[RunReview] 仓库已 clone 到: {repo_manager.clone_path}")\n \n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/graph/builder.py',
    'old_path': 'app/graph/builder.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,3 +1,15 @@\n+"""\n+LangGraph 节点实现\n+每个节点是图中的一个处理步骤。\n+\n+节点列表：\n+- prepare: Harness 层处理（解析 → 过滤 → 分组 → 规则匹配）\n+- run_critic: 运行单个 Critic ReAct Agent\n+- aggregate: 合并去重所有 Critic 的 findings\n+- reflect: Reflector 验证 critical/warning findings\n+- report: 计算风险分 + 生成输出\n+"""\n+\n \n import json\n import logging\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/graph/nodes.py',
    'old_path': 'app/graph/nodes.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,4 +1,12 @@\n-\n+"""\n+LangGraph 状态定义\n+State 是图中所有节点共享的数据结构，每个节点读取 + 修改 State。\n+\n+设计意图：\n+- 输入字段：Webhook 传入的原始数据\n+- 中间字段：各节点产出的中间结果\n+- 输出字段：最终审查报告\n+"""\n \n import operator\n from typing import Annotated, Any, Optional\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/graph/state.py',
    'old_path': 'app/graph/state.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,3 +1,45 @@\n+"""2\n+Diff 解析器\n+将 GitLab MR changes API 返回的 JSON 解析为结构化 FileChange 列表。\n+\n+GitLab 返回格式：\n+[\n+  {\n+    "old_path": "src/user.py",\n+    "new_path": "src/user.py",\n+    "diff": "--- a/src/user.py\\n+++ b/src/user.py\\n@@ -1,3 +1,4 @@\\n...",\n+    "new_file": false,\n+    "deleted_file": false,\n+    "renamed_file": false\n+  },\n+  ...\n+]\n+\n+\n+# 输入：GitLab API 返回的 JSON\n+changes = [\n+    {\n+        "new_path": "src/auth/login.py",\n+        "old_path": "src/auth/login.py",\n+        "diff": "@@ -10,4 +10,6 @@\\n def login(username, password):\\n-    user = User.query.filter_by(name=username).first()\\n+    user = User.query.filter_by(name=username)\\n+    if not user:\\n+        return None\\n     return generate_token(user)",\n+        "new_file": False,\n+        "deleted_file": False,\n+        "renamed_file": False,\n+    }\n+]\n+\n+# 输出：结构化 FileChange\n+FileChange(\n+    path="src/auth/login.py",\n+    language="python",\n+    changed_lines=4,          # 1行删除 + 3行新增\n+    is_new=False,\n+    is_deleted=False,\n+    hunks=[Hunk(old_start=10, old_lines=4, new_start=10, new_lines=6, content="...")],\n+    diff_text="@@ -10,4 +10,6 @@\\n def login(..."  # 原始文本保留\n+)\n+"""\n+\n import re\n import logging\n from dataclasses import dataclass, field\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/harness/diff_parser.py',
    'old_path': 'app/harness/diff_parser.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,3 +1,30 @@\n+"""3\n+文件过滤器\n+确定性规则过滤不需要审查的文件。\n+这是 Harness 层"必须做到的事"——不依赖 LLM 判断。\n+\n+过滤逻辑参考阿里 OCR：精确文件选择，确保不浪费 token 在垃圾文件上。\n+\n+\n+# 输入：4 个 FileChange\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=4),\n+    FileChange(path="package-lock.json", changed_lines=3000),\n+    FileChange(path="src/auth/logo.png", changed_lines=0, is_deleted=False),\n+    FileChange(path="old_helper.py", changed_lines=0, is_deleted=True),\n+]\n+\n+# 输出：只剩 1 个\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=4),\n+]\n+\n+# 被过滤的原因：\n+# package-lock.json → 命中 lock 文件正则\n+# logo.png → 命中图片后缀正则\n+# old_helper.py → is_deleted=True（删除的文件审查价值低）\n+"""\n+\n import re\n import logging\n from app.harness.diff_parser import FileChange\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/harness/file_filter.py',
    'old_path': 'app/harness/file_filter.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,3 +1,30 @@\n+"""4\n+文件分组器\n+将变更文件列表按行数阈值分为多个 bundle。\n+\n+核心规则（面试要能讲清楚）：\n+1. 文件是最小单位，永远不会被拆分\n+2. 单文件超过阈值 → 独占一个 bundle\n+3. 多个小文件打包到一起，直到接近阈值\n+4. 阈值默认 800 行（保证 LLM 注意力质量）\n+\n+\n+# 输入：过滤后的文件列表（假设剩 6 个文件）\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=200),\n+    FileChange(path="src/auth/token.py", changed_lines=150),\n+    FileChange(path="src/api/routes.py", changed_lines=300),\n+    FileChange(path="src/models/user.py", changed_lines=100),\n+    FileChange(path="src/utils/helper.py", changed_lines=50),\n+    FileChange(path="src/legacy/old_module.py", changed_lines=900),  # 大文件！\n+]\n+\n+# 输出：3 个 Bundle（阈值 800 行）\n+Bundle 1: [src/legacy/old_module.py]           (900行，独占)\n+Bundle 2: [src/api/routes.py, src/auth/login.py, src/auth/token.py]  (650行)\n+Bundle 3: [src/models/user.py, src/utils/helper.py]                  (150行)\n+(打bundle主要是考虑成本因素，减少多次请求的token消耗)\n+"""\n \n import logging\n from dataclasses import dataclass, field\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/harness/file_grouper.py',
    'old_path': 'app/harness/file_grouper.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,7 +1,26 @@\n+"""1\n+仓库管理器\n+负责 git clone 到本地临时目录，审查结束后清理。\n+工具层（read_file/grep）操作的就是这里 clone 下来的本地文件。\n+\n+\n+输入：\n+  repo_url = "https://gitlab.com/team/project.git"\n+  branch = "feature/add-login"\n+\n+执行：\n+  git clone --depth=1 --single-branch --branch feature/add-login \\\n+      https://gitlab.com/team/project.git /tmp/devbot_repos/abc123/\n+\n+输出：\n+  clone_path = Path("/tmp/devbot_repos/abc123/")\n+  → 后续 read_file / grep 工具都在这个目录下操作\n+"""\n \n import asyncio\n import logging\n import shutil\n+import subprocess\n import tempfile\n from pathlib import Path\n \n@@ -33,6 +52,8 @@ class RepoManager:\n         base_dir.mkdir(parents=True, exist_ok=True)\n \n         self._clone_path = Path(tempfile.mkdtemp(dir=base_dir))\n+        # mkdtemp 会创建目录，但 git clone 要求目标不存在，先删掉\n+        shutil.rmtree(self._clone_path)\n         logger.info(f"[Repo] 开始 clone → {self._clone_path}")\n         logger.debug(f"[Repo] 命令: git clone --depth=1 --single-branch --branch {branch}")\n \n@@ -45,16 +66,18 @@ class RepoManager:\n             str(self._clone_path),\n         ]\n \n-        process = await asyncio.create_subprocess_exec(\n-            *cmd,\n-            stdout=asyncio.subprocess.PIPE,\n-            stderr=asyncio.subprocess.PIPE,\n+        # Windows 上 asyncio.create_subprocess_exec 不兼容 uvicorn 事件循环\n+        # 改用 run_in_executor + subprocess.run 保证跨平台兼容\n+        loop = asyncio.get_event_loop()\n+        result = await loop.run_in_executor(\n+            None,\n+            lambda: subprocess.run(cmd, capture_output=True, timeout=120),\n         )\n-        _, stderr = await process.communicate()\n \n-        if process.returncode != 0:\n-            logger.error(f"[Repo] clone 失败: {stderr.decode()[:200]}")\n-            raise RuntimeError(f"git clone failed: {stderr.decode()}")\n+        if result.returncode != 0:\n+            err_msg = result.stderr.decode(errors="replace")[:200]\n+            logger.error(f"[Repo] clone 失败: {err_msg}")\n+            raise RuntimeError(f"git clone failed: {err_msg}")\n \n         logger.info(f"[Repo] clone 完成: {self._clone_path}")\n         return self._clone_path\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/harness/repo_manager.py',
    'old_path': 'app/harness/repo_manager.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,3 +1,27 @@\n+"""5\n+规则匹配器\n+根据文件语言和路径，注入对应的审查规则到 Critic prompt 中。\n+\n+这是 Harness 层的"确定性规则注入"——\n+不让 LLM 自己决定关注什么规则，而是工程逻辑预先匹配好。\n+参考阿里 OCR 的模板引擎规则匹配思路（但简化为 Python dict）。\n+\n+\n+# 输入：Bundle 2 的文件列表\n+[\n+    FileChange(path="src/api/routes.py", language="python"),\n+    FileChange(path="src/auth/login.py", language="python"),\n+]\n+\n+# 输出：拼接到 Critic prompt 里的规则文本\n+\n+【本次审查需重点关注的规则】\n+  - 检查异常处理：是否有裸 except、是否吞掉了异常\n+  - 检查接口参数校验是否完整        ← 因为路径匹配了 /api/\n+  - 检查是否缺少类型注解（函数参数和返回值）\n+  - 检查资源管理：文件/连接是否使用 with 语句\n+  - 检查鉴权中间件是否生效          ← 因为路径匹配了 route\n+"""\n \n import logging\n from app.harness.diff_parser import FileChange\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/harness/rule_matcher.py',
    'old_path': 'app/harness/rule_matcher.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,3 +1,14 @@\n+"""\n+Prompt Registry\n+加载 YAML prompt 模板并填充运行时变量。\n+\n+设计意图：\n+- Prompt 外置为 YAML 文件，修改 prompt 不用改 Python 代码\n+- 统一加载接口，Critic/Reflector 通过名字获取 prompt\n+- 模板变量用 str.format() 填充（{diff_text}、{rules} 等）\n+"""\n+\n+\n from pathlib import Path\n from dataclasses import dataclass\n import logging\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/prompts/registry.py',
    'old_path': 'app/prompts/registry.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,4 +1,15 @@\n-\n+"""\n+工具层：Critic 的 3 个核心工具\n+- read_file: 读取仓库文件（整个 clone 下来的仓库）\n+- grep: 正则搜索仓库代码\n+- get_diff_file: 获取 MR 中指定变更文件的 diff\n+\n+设计原则：\n+1. 工厂模式 —— 运行时注入 repo_manager 和 file_changes 依赖\n+2. 路径安全 —— 防止 LLM 构造路径逃逸（../../etc/passwd）\n+3. 输出截断 —— 防止超大文件撑爆 token budget\n+4. LangChain StructuredTool —— 直接接入 LangGraph ReAct Agent\n+"""\n \n import re\n import logging\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/tools/code_tools.py',
    'old_path': 'app/tools/code_tools.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,4 +1,8 @@\n-\n+"""\n+DevBot 配置管理\n+所有敏感信息通过环境变量注入，不硬编码。\n+面试点：12-Factor App 配置外置原则。\n+"""\n \n from pydantic_settings import BaseSettings\n from functools import lru_cache\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/config.py',
    'old_path': 'app/config.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}, {
    'diff': '@@ -1,3 +1,7 @@\n+"""\n+DevBot — FastAPI 入口\n+接收 GitLab Webhook，异步触发 MR 评审流程。\n+"""\n \n import logging\n import sys\n',
    'collapsed': False,
    'too_large': False,
    'new_path': 'app/main.py',
    'old_path': 'app/main.py',
    'a_mode': '100644',
    'b_mode': '100644',
    'new_file': False,
    'renamed_file': False,
    'deleted_file': False,
    'generated_file': False
}]


let parse_gitlab_changes = [
    FileChange(
        path = 'app/gitlab/client.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 4,
                new_start = 1,
                new_lines = 12,
                content = '@@ -1,4 +1,12 @@\n+"""\n+GitLab API 客户端\n+封装 MR 评论、Commit Status、获取 diff 等操作。\n \n+GitLab API 特点（vs GitHub）：\n+- 项目用 ID 或 URL-encoded path 标识（如 group%2Fproject）\n+- 行级评论通过 Discussions API 实现\n+- Commit Status API 参数略有不同\n+"""\n \n import logging\n import httpx'
            ),
            Hunk(
                old_start = 43,
                old_lines = 6,
                new_start = 51,
                new_lines = 10,
                content = '@@ -43,6 +51,10 @@ class GitLabClient:\n         创建行级评论（通过 Discussion API）。\n         GitLab 行级评论需要 position 对象，比 GitHub 复杂。\n         """\n+        if not new_line or new_line < 1:\n+            logger.warning(f"[GitLab] 行号无效({new_line})，跳过行级评论: {new_path}")\n+            return\n+\n         url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/discussions"\n         payload = {\n             "body": body,'
            ),
            Hunk(
                old_start = 51,
                old_lines = 6,
                new_start = 63,
                new_lines = 7,
                content = '@@ -51,6 +63,7 @@ class GitLabClient:\n                 "head_sha": head_sha,\n                 "start_sha": start_sha,\n                 "position_type": "text",\n+                "old_path": new_path,\n                 "new_path": new_path,\n                 "new_line": new_line,\n             },'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 13,
        diff_text = '@@ -1,4 +1,12 @@\n+"""\n+GitLab API 客户端\n+封装 MR 评论、Commit Status、获取 diff 等操作。\n \n+GitLab API 特点（vs GitHub）：\n+- 项目用 ID 或 URL-encoded path 标识（如 group%2Fproject）\n+- 行级评论通过 Discussions API 实现\n+- Commit Status API 参数略有不同\n+"""\n \n import logging\n import httpx\n@@ -43,6 +51,10 @@ class GitLabClient:\n         创建行级评论（通过 Discussion API）。\n         GitLab 行级评论需要 position 对象，比 GitHub 复杂。\n         """\n+        if not new_line or new_line < 1:\n+            logger.warning(f"[GitLab] 行号无效({new_line})，跳过行级评论: {new_path}")\n+            return\n+\n         url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/discussions"\n         payload = {\n             "body": body,\n@@ -51,6 +63,7 @@ class GitLabClient:\n                 "head_sha": head_sha,\n                 "start_sha": start_sha,\n                 "position_type": "text",\n+                "old_path": new_path,\n                 "new_path": new_path,\n                 "new_line": new_line,\n             },'
    ),
    FileChange(
        path = 'app/gitlab/webhook.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 4,
                new_start = 1,
                new_lines = 17,
                content = '@@ -1,4 +1,17 @@\n-\n+"""\n+GitLab Webhook 路由\n+接收 MR 事件，X-Gitlab-Token 校验，异步触发评审。\n+\n+完整流程：\n+  Webhook → 校验 → 过滤事件 → 异步触发 _run_review()\n+  _run_review():\n+    1. 获取 MR 详情（sha、branch、repo URL）\n+    2. 获取 MR diff（changes JSON）\n+    3. 设置 Commit Status = "running"\n+    4. 调用 LangGraph 审查图（run_review）\n+    5. 发布审查结果（摘要 + 行级评论）\n+    6. 设置 Commit Status = "success" / "failed"\n+"""\n import asyncio\n import logging\n '
            ),
            Hunk(
                old_start = 68,
                old_lines = 7,
                new_start = 81,
                new_lines = 7,
                content = '@@ -68,7 +81,7 @@ async def _run_review(webhook_data: dict):\n \n     logger.info(f"[审查] ══ 开始 ══ Project #{project_id} MR !{mr_iid}")\n     logger.info(f"[审查] 分支: {source_branch} | head_sha: {head_sha[:12]}...")\n-    logger.debug(f"[审查] repo_url: {repo_url[:50]}...")\n+    logger.debug(f"[审查] repo_url: {repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:50]}...")\n \n     try:\n '
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 17,
        diff_text = '@@ -1,4 +1,17 @@\n-\n+"""\n+GitLab Webhook 路由\n+接收 MR 事件，X-Gitlab-Token 校验，异步触发评审。\n+\n+完整流程：\n+  Webhook → 校验 → 过滤事件 → 异步触发 _run_review()\n+  _run_review():\n+    1. 获取 MR 详情（sha、branch、repo URL）\n+    2. 获取 MR diff（changes JSON）\n+    3. 设置 Commit Status = "running"\n+    4. 调用 LangGraph 审查图（run_review）\n+    5. 发布审查结果（摘要 + 行级评论）\n+    6. 设置 Commit Status = "success" / "failed"\n+"""\n import asyncio\n import logging\n \n@@ -68,7 +81,7 @@ async def _run_review(webhook_data: dict):\n \n     logger.info(f"[审查] ══ 开始 ══ Project #{project_id} MR !{mr_iid}")\n     logger.info(f"[审查] 分支: {source_branch} | head_sha: {head_sha[:12]}...")\n-    logger.debug(f"[审查] repo_url: {repo_url[:50]}...")\n+    logger.debug(f"[审查] repo_url: {repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:50]}...")\n \n     try:\n \n'
    ),
    FileChange(
        path = 'app/graph/builder.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 4,
                new_start = 1,
                new_lines = 15,
                content = '@@ -1,4 +1,15 @@\n+"""\n+LangGraph 图构建器\n+将所有节点组装为完整的审查流水线。\n \n+图结构：\n+  prepare ──→ Send × 4 Critics（并行）──→ aggregate ──→ reflect ──→ report\n+\n+关键机制：\n+- Send API: 确定性扇出到 4 个 Critic（不是 LLM 决定启动几个，是工程逻辑决定）\n+- operator.add reducer: 并行 Critic 的结果自动合并到 critic_results 列表\n+- 异步执行: Critic 和 Reflector 是 async 节点（LLM 调用）\n+"""\n \n import logging\n from typing import Any'
            ),
            Hunk(
                old_start = 160,
                old_lines = 7,
                new_start = 171,
                new_lines = 8,
                content = '@@ -160,7 +171,8 @@ async def run_review(\n \n     repo_manager = RepoManager()\n     try:\n-        logger.info(f"[RunReview] 开始 clone 仓库: {repo_url[:60]}... branch={branch}")\n+        safe_url = repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:60]\n+        logger.info(f"[RunReview] 开始 clone 仓库: {safe_url} | branch={branch}")\n         await repo_manager.clone(repo_url, branch)\n         logger.info(f"[RunReview] 仓库已 clone 到: {repo_manager.clone_path}")\n '
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 14,
        diff_text = '@@ -1,4 +1,15 @@\n+"""\n+LangGraph 图构建器\n+将所有节点组装为完整的审查流水线。\n \n+图结构：\n+  prepare ──→ Send × 4 Critics（并行）──→ aggregate ──→ reflect ──→ report\n+\n+关键机制：\n+- Send API: 确定性扇出到 4 个 Critic（不是 LLM 决定启动几个，是工程逻辑决定）\n+- operator.add reducer: 并行 Critic 的结果自动合并到 critic_results 列表\n+- 异步执行: Critic 和 Reflector 是 async 节点（LLM 调用）\n+"""\n \n import logging\n from typing import Any\n@@ -160,7 +171,8 @@ async def run_review(\n \n     repo_manager = RepoManager()\n     try:\n-        logger.info(f"[RunReview] 开始 clone 仓库: {repo_url[:60]}... branch={branch}")\n+        safe_url = repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:60]\n+        logger.info(f"[RunReview] 开始 clone 仓库: {safe_url} | branch={branch}")\n         await repo_manager.clone(repo_url, branch)\n         logger.info(f"[RunReview] 仓库已 clone 到: {repo_manager.clone_path}")\n \n'
    ),
    FileChange(
        path = 'app/graph/nodes.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 3,
                new_start = 1,
                new_lines = 15,
                content = '@@ -1,3 +1,15 @@\n+"""\n+LangGraph 节点实现\n+每个节点是图中的一个处理步骤。\n+\n+节点列表：\n+- prepare: Harness 层处理（解析 → 过滤 → 分组 → 规则匹配）\n+- run_critic: 运行单个 Critic ReAct Agent\n+- aggregate: 合并去重所有 Critic 的 findings\n+- reflect: Reflector 验证 critical/warning findings\n+- report: 计算风险分 + 生成输出\n+"""\n+\n \n import json\n import logging'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 12,
        diff_text = '@@ -1,3 +1,15 @@\n+"""\n+LangGraph 节点实现\n+每个节点是图中的一个处理步骤。\n+\n+节点列表：\n+- prepare: Harness 层处理（解析 → 过滤 → 分组 → 规则匹配）\n+- run_critic: 运行单个 Critic ReAct Agent\n+- aggregate: 合并去重所有 Critic 的 findings\n+- reflect: Reflector 验证 critical/warning findings\n+- report: 计算风险分 + 生成输出\n+"""\n+\n \n import json\n import logging\n'
    ),
    FileChange(
        path = 'app/graph/state.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 4,
                new_start = 1,
                new_lines = 12,
                content = '@@ -1,4 +1,12 @@\n-\n+"""\n+LangGraph 状态定义\n+State 是图中所有节点共享的数据结构，每个节点读取 + 修改 State。\n+\n+设计意图：\n+- 输入字段：Webhook 传入的原始数据\n+- 中间字段：各节点产出的中间结果\n+- 输出字段：最终审查报告\n+"""\n \n import operator\n from typing import Annotated, Any, Optional'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 10,
        diff_text = '@@ -1,4 +1,12 @@\n-\n+"""\n+LangGraph 状态定义\n+State 是图中所有节点共享的数据结构，每个节点读取 + 修改 State。\n+\n+设计意图：\n+- 输入字段：Webhook 传入的原始数据\n+- 中间字段：各节点产出的中间结果\n+- 输出字段：最终审查报告\n+"""\n \n import operator\n from typing import Annotated, Any, Optional\n'
    ),
    FileChange(
        path = 'app/harness/diff_parser.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 3,
                new_start = 1,
                new_lines = 45,
                content = '@@ -1,3 +1,45 @@\n+"""2\n+Diff 解析器\n+将 GitLab MR changes API 返回的 JSON 解析为结构化 FileChange 列表。\n+\n+GitLab 返回格式：\n+[\n+  {\n+    "old_path": "src/user.py",\n+    "new_path": "src/user.py",\n+    "diff": "--- a/src/user.py\\n+++ b/src/user.py\\n@@ -1,3 +1,4 @@\\n...",\n+    "new_file": false,\n+    "deleted_file": false,\n+    "renamed_file": false\n+  },\n+  ...\n+]\n+\n+\n+# 输入：GitLab API 返回的 JSON\n+changes = [\n+    {\n+        "new_path": "src/auth/login.py",\n+        "old_path": "src/auth/login.py",\n+        "diff": "@@ -10,4 +10,6 @@\\n def login(username, password):\\n-    user = User.query.filter_by(name=username).first()\\n+    user = User.query.filter_by(name=username)\\n+    if not user:\\n+        return None\\n     return generate_token(user)",\n+        "new_file": False,\n+        "deleted_file": False,\n+        "renamed_file": False,\n+    }\n+]\n+\n+# 输出：结构化 FileChange\n+FileChange(\n+    path="src/auth/login.py",\n+    language="python",\n+    changed_lines=4,          # 1行删除 + 3行新增\n+    is_new=False,\n+    is_deleted=False,\n+    hunks=[Hunk(old_start=10, old_lines=4, new_start=10, new_lines=6, content="...")],\n+    diff_text="@@ -10,4 +10,6 @@\\n def login(..."  # 原始文本保留\n+)\n+"""\n+\n import re\n import logging\n from dataclasses import dataclass, field'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 42,
        diff_text = '@@ -1,3 +1,45 @@\n+"""2\n+Diff 解析器\n+将 GitLab MR changes API 返回的 JSON 解析为结构化 FileChange 列表。\n+\n+GitLab 返回格式：\n+[\n+  {\n+    "old_path": "src/user.py",\n+    "new_path": "src/user.py",\n+    "diff": "--- a/src/user.py\\n+++ b/src/user.py\\n@@ -1,3 +1,4 @@\\n...",\n+    "new_file": false,\n+    "deleted_file": false,\n+    "renamed_file": false\n+  },\n+  ...\n+]\n+\n+\n+# 输入：GitLab API 返回的 JSON\n+changes = [\n+    {\n+        "new_path": "src/auth/login.py",\n+        "old_path": "src/auth/login.py",\n+        "diff": "@@ -10,4 +10,6 @@\\n def login(username, password):\\n-    user = User.query.filter_by(name=username).first()\\n+    user = User.query.filter_by(name=username)\\n+    if not user:\\n+        return None\\n     return generate_token(user)",\n+        "new_file": False,\n+        "deleted_file": False,\n+        "renamed_file": False,\n+    }\n+]\n+\n+# 输出：结构化 FileChange\n+FileChange(\n+    path="src/auth/login.py",\n+    language="python",\n+    changed_lines=4,          # 1行删除 + 3行新增\n+    is_new=False,\n+    is_deleted=False,\n+    hunks=[Hunk(old_start=10, old_lines=4, new_start=10, new_lines=6, content="...")],\n+    diff_text="@@ -10,4 +10,6 @@\\n def login(..."  # 原始文本保留\n+)\n+"""\n+\n import re\n import logging\n from dataclasses import dataclass, field\n'
    ),
    FileChange(
        path = 'app/harness/file_filter.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 3,
                new_start = 1,
                new_lines = 30,
                content = '@@ -1,3 +1,30 @@\n+"""3\n+文件过滤器\n+确定性规则过滤不需要审查的文件。\n+这是 Harness 层"必须做到的事"——不依赖 LLM 判断。\n+\n+过滤逻辑参考阿里 OCR：精确文件选择，确保不浪费 token 在垃圾文件上。\n+\n+\n+# 输入：4 个 FileChange\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=4),\n+    FileChange(path="package-lock.json", changed_lines=3000),\n+    FileChange(path="src/auth/logo.png", changed_lines=0, is_deleted=False),\n+    FileChange(path="old_helper.py", changed_lines=0, is_deleted=True),\n+]\n+\n+# 输出：只剩 1 个\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=4),\n+]\n+\n+# 被过滤的原因：\n+# package-lock.json → 命中 lock 文件正则\n+# logo.png → 命中图片后缀正则\n+# old_helper.py → is_deleted=True（删除的文件审查价值低）\n+"""\n+\n import re\n import logging\n from app.harness.diff_parser import FileChange'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 27,
        diff_text = '@@ -1,3 +1,30 @@\n+"""3\n+文件过滤器\n+确定性规则过滤不需要审查的文件。\n+这是 Harness 层"必须做到的事"——不依赖 LLM 判断。\n+\n+过滤逻辑参考阿里 OCR：精确文件选择，确保不浪费 token 在垃圾文件上。\n+\n+\n+# 输入：4 个 FileChange\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=4),\n+    FileChange(path="package-lock.json", changed_lines=3000),\n+    FileChange(path="src/auth/logo.png", changed_lines=0, is_deleted=False),\n+    FileChange(path="old_helper.py", changed_lines=0, is_deleted=True),\n+]\n+\n+# 输出：只剩 1 个\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=4),\n+]\n+\n+# 被过滤的原因：\n+# package-lock.json → 命中 lock 文件正则\n+# logo.png → 命中图片后缀正则\n+# old_helper.py → is_deleted=True（删除的文件审查价值低）\n+"""\n+\n import re\n import logging\n from app.harness.diff_parser import FileChange\n'
    ),
    FileChange(
        path = 'app/harness/file_grouper.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 3,
                new_start = 1,
                new_lines = 30,
                content = '@@ -1,3 +1,30 @@\n+"""4\n+文件分组器\n+将变更文件列表按行数阈值分为多个 bundle。\n+\n+核心规则（面试要能讲清楚）：\n+1. 文件是最小单位，永远不会被拆分\n+2. 单文件超过阈值 → 独占一个 bundle\n+3. 多个小文件打包到一起，直到接近阈值\n+4. 阈值默认 800 行（保证 LLM 注意力质量）\n+\n+\n+# 输入：过滤后的文件列表（假设剩 6 个文件）\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=200),\n+    FileChange(path="src/auth/token.py", changed_lines=150),\n+    FileChange(path="src/api/routes.py", changed_lines=300),\n+    FileChange(path="src/models/user.py", changed_lines=100),\n+    FileChange(path="src/utils/helper.py", changed_lines=50),\n+    FileChange(path="src/legacy/old_module.py", changed_lines=900),  # 大文件！\n+]\n+\n+# 输出：3 个 Bundle（阈值 800 行）\n+Bundle 1: [src/legacy/old_module.py]           (900行，独占)\n+Bundle 2: [src/api/routes.py, src/auth/login.py, src/auth/token.py]  (650行)\n+Bundle 3: [src/models/user.py, src/utils/helper.py]                  (150行)\n+(打bundle主要是考虑成本因素，减少多次请求的token消耗)\n+"""\n \n import logging\n from dataclasses import dataclass, field'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 27,
        diff_text = '@@ -1,3 +1,30 @@\n+"""4\n+文件分组器\n+将变更文件列表按行数阈值分为多个 bundle。\n+\n+核心规则（面试要能讲清楚）：\n+1. 文件是最小单位，永远不会被拆分\n+2. 单文件超过阈值 → 独占一个 bundle\n+3. 多个小文件打包到一起，直到接近阈值\n+4. 阈值默认 800 行（保证 LLM 注意力质量）\n+\n+\n+# 输入：过滤后的文件列表（假设剩 6 个文件）\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=200),\n+    FileChange(path="src/auth/token.py", changed_lines=150),\n+    FileChange(path="src/api/routes.py", changed_lines=300),\n+    FileChange(path="src/models/user.py", changed_lines=100),\n+    FileChange(path="src/utils/helper.py", changed_lines=50),\n+    FileChange(path="src/legacy/old_module.py", changed_lines=900),  # 大文件！\n+]\n+\n+# 输出：3 个 Bundle（阈值 800 行）\n+Bundle 1: [src/legacy/old_module.py]           (900行，独占)\n+Bundle 2: [src/api/routes.py, src/auth/login.py, src/auth/token.py]  (650行)\n+Bundle 3: [src/models/user.py, src/utils/helper.py]                  (150行)\n+(打bundle主要是考虑成本因素，减少多次请求的token消耗)\n+"""\n \n import logging\n from dataclasses import dataclass, field\n'
    ),
    FileChange(
        path = 'app/harness/repo_manager.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 7,
                new_start = 1,
                new_lines = 26,
                content = '@@ -1,7 +1,26 @@\n+"""1\n+仓库管理器\n+负责 git clone 到本地临时目录，审查结束后清理。\n+工具层（read_file/grep）操作的就是这里 clone 下来的本地文件。\n+\n+\n+输入：\n+  repo_url = "https://gitlab.com/team/project.git"\n+  branch = "feature/add-login"\n+\n+执行：\n+  git clone --depth=1 --single-branch --branch feature/add-login \\\n+      https://gitlab.com/team/project.git /tmp/devbot_repos/abc123/\n+\n+输出：\n+  clone_path = Path("/tmp/devbot_repos/abc123/")\n+  → 后续 read_file / grep 工具都在这个目录下操作\n+"""\n \n import asyncio\n import logging\n import shutil\n+import subprocess\n import tempfile\n from pathlib import Path\n '
            ),
            Hunk(
                old_start = 33,
                old_lines = 6,
                new_start = 52,
                new_lines = 8,
                content = '@@ -33,6 +52,8 @@ class RepoManager:\n         base_dir.mkdir(parents=True, exist_ok=True)\n \n         self._clone_path = Path(tempfile.mkdtemp(dir=base_dir))\n+        # mkdtemp 会创建目录，但 git clone 要求目标不存在，先删掉\n+        shutil.rmtree(self._clone_path)\n         logger.info(f"[Repo] 开始 clone → {self._clone_path}")\n         logger.debug(f"[Repo] 命令: git clone --depth=1 --single-branch --branch {branch}")\n '
            ),
            Hunk(
                old_start = 45,
                old_lines = 16,
                new_start = 66,
                new_lines = 18,
                content = '@@ -45,16 +66,18 @@ class RepoManager:\n             str(self._clone_path),\n         ]\n \n-        process = await asyncio.create_subprocess_exec(\n-            *cmd,\n-            stdout=asyncio.subprocess.PIPE,\n-            stderr=asyncio.subprocess.PIPE,\n+        # Windows 上 asyncio.create_subprocess_exec 不兼容 uvicorn 事件循环\n+        # 改用 run_in_executor + subprocess.run 保证跨平台兼容\n+        loop = asyncio.get_event_loop()\n+        result = await loop.run_in_executor(\n+            None,\n+            lambda: subprocess.run(cmd, capture_output=True, timeout=120),\n         )\n-        _, stderr = await process.communicate()\n \n-        if process.returncode != 0:\n-            logger.error(f"[Repo] clone 失败: {stderr.decode()[:200]}")\n-            raise RuntimeError(f"git clone failed: {stderr.decode()}")\n+        if result.returncode != 0:\n+            err_msg = result.stderr.decode(errors="replace")[:200]\n+            logger.error(f"[Repo] clone 失败: {err_msg}")\n+            raise RuntimeError(f"git clone failed: {err_msg}")\n \n         logger.info(f"[Repo] clone 完成: {self._clone_path}")\n         return self._clone_path'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 39,
        diff_text = '@@ -1,7 +1,26 @@\n+"""1\n+仓库管理器\n+负责 git clone 到本地临时目录，审查结束后清理。\n+工具层（read_file/grep）操作的就是这里 clone 下来的本地文件。\n+\n+\n+输入：\n+  repo_url = "https://gitlab.com/team/project.git"\n+  branch = "feature/add-login"\n+\n+执行：\n+  git clone --depth=1 --single-branch --branch feature/add-login \\\n+      https://gitlab.com/team/project.git /tmp/devbot_repos/abc123/\n+\n+输出：\n+  clone_path = Path("/tmp/devbot_repos/abc123/")\n+  → 后续 read_file / grep 工具都在这个目录下操作\n+"""\n \n import asyncio\n import logging\n import shutil\n+import subprocess\n import tempfile\n from pathlib import Path\n \n@@ -33,6 +52,8 @@ class RepoManager:\n         base_dir.mkdir(parents=True, exist_ok=True)\n \n         self._clone_path = Path(tempfile.mkdtemp(dir=base_dir))\n+        # mkdtemp 会创建目录，但 git clone 要求目标不存在，先删掉\n+        shutil.rmtree(self._clone_path)\n         logger.info(f"[Repo] 开始 clone → {self._clone_path}")\n         logger.debug(f"[Repo] 命令: git clone --depth=1 --single-branch --branch {branch}")\n \n@@ -45,16 +66,18 @@ class RepoManager:\n             str(self._clone_path),\n         ]\n \n-        process = await asyncio.create_subprocess_exec(\n-            *cmd,\n-            stdout=asyncio.subprocess.PIPE,\n-            stderr=asyncio.subprocess.PIPE,\n+        # Windows 上 asyncio.create_subprocess_exec 不兼容 uvicorn 事件循环\n+        # 改用 run_in_executor + subprocess.run 保证跨平台兼容\n+        loop = asyncio.get_event_loop()\n+        result = await loop.run_in_executor(\n+            None,\n+            lambda: subprocess.run(cmd, capture_output=True, timeout=120),\n         )\n-        _, stderr = await process.communicate()\n \n-        if process.returncode != 0:\n-            logger.error(f"[Repo] clone 失败: {stderr.decode()[:200]}")\n-            raise RuntimeError(f"git clone failed: {stderr.decode()}")\n+        if result.returncode != 0:\n+            err_msg = result.stderr.decode(errors="replace")[:200]\n+            logger.error(f"[Repo] clone 失败: {err_msg}")\n+            raise RuntimeError(f"git clone failed: {err_msg}")\n \n         logger.info(f"[Repo] clone 完成: {self._clone_path}")\n         return self._clone_path\n'
    ),
    FileChange(
        path = 'app/harness/rule_matcher.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 3,
                new_start = 1,
                new_lines = 27,
                content = '@@ -1,3 +1,27 @@\n+"""5\n+规则匹配器\n+根据文件语言和路径，注入对应的审查规则到 Critic prompt 中。\n+\n+这是 Harness 层的"确定性规则注入"——\n+不让 LLM 自己决定关注什么规则，而是工程逻辑预先匹配好。\n+参考阿里 OCR 的模板引擎规则匹配思路（但简化为 Python dict）。\n+\n+\n+# 输入：Bundle 2 的文件列表\n+[\n+    FileChange(path="src/api/routes.py", language="python"),\n+    FileChange(path="src/auth/login.py", language="python"),\n+]\n+\n+# 输出：拼接到 Critic prompt 里的规则文本\n+\n+【本次审查需重点关注的规则】\n+  - 检查异常处理：是否有裸 except、是否吞掉了异常\n+  - 检查接口参数校验是否完整        ← 因为路径匹配了 /api/\n+  - 检查是否缺少类型注解（函数参数和返回值）\n+  - 检查资源管理：文件/连接是否使用 with 语句\n+  - 检查鉴权中间件是否生效          ← 因为路径匹配了 route\n+"""\n \n import logging\n from app.harness.diff_parser import FileChange'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 24,
        diff_text = '@@ -1,3 +1,27 @@\n+"""5\n+规则匹配器\n+根据文件语言和路径，注入对应的审查规则到 Critic prompt 中。\n+\n+这是 Harness 层的"确定性规则注入"——\n+不让 LLM 自己决定关注什么规则，而是工程逻辑预先匹配好。\n+参考阿里 OCR 的模板引擎规则匹配思路（但简化为 Python dict）。\n+\n+\n+# 输入：Bundle 2 的文件列表\n+[\n+    FileChange(path="src/api/routes.py", language="python"),\n+    FileChange(path="src/auth/login.py", language="python"),\n+]\n+\n+# 输出：拼接到 Critic prompt 里的规则文本\n+\n+【本次审查需重点关注的规则】\n+  - 检查异常处理：是否有裸 except、是否吞掉了异常\n+  - 检查接口参数校验是否完整        ← 因为路径匹配了 /api/\n+  - 检查是否缺少类型注解（函数参数和返回值）\n+  - 检查资源管理：文件/连接是否使用 with 语句\n+  - 检查鉴权中间件是否生效          ← 因为路径匹配了 route\n+"""\n \n import logging\n from app.harness.diff_parser import FileChange\n'
    ),
    FileChange(
        path = 'app/prompts/registry.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 3,
                new_start = 1,
                new_lines = 14,
                content = '@@ -1,3 +1,14 @@\n+"""\n+Prompt Registry\n+加载 YAML prompt 模板并填充运行时变量。\n+\n+设计意图：\n+- Prompt 外置为 YAML 文件，修改 prompt 不用改 Python 代码\n+- 统一加载接口，Critic/Reflector 通过名字获取 prompt\n+- 模板变量用 str.format() 填充（{diff_text}、{rules} 等）\n+"""\n+\n+\n from pathlib import Path\n from dataclasses import dataclass\n import logging'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 11,
        diff_text = '@@ -1,3 +1,14 @@\n+"""\n+Prompt Registry\n+加载 YAML prompt 模板并填充运行时变量。\n+\n+设计意图：\n+- Prompt 外置为 YAML 文件，修改 prompt 不用改 Python 代码\n+- 统一加载接口，Critic/Reflector 通过名字获取 prompt\n+- 模板变量用 str.format() 填充（{diff_text}、{rules} 等）\n+"""\n+\n+\n from pathlib import Path\n from dataclasses import dataclass\n import logging\n'
    ),
    FileChange(
        path = 'app/tools/code_tools.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 4,
                new_start = 1,
                new_lines = 15,
                content = '@@ -1,4 +1,15 @@\n-\n+"""\n+工具层：Critic 的 3 个核心工具\n+- read_file: 读取仓库文件（整个 clone 下来的仓库）\n+- grep: 正则搜索仓库代码\n+- get_diff_file: 获取 MR 中指定变更文件的 diff\n+\n+设计原则：\n+1. 工厂模式 —— 运行时注入 repo_manager 和 file_changes 依赖\n+2. 路径安全 —— 防止 LLM 构造路径逃逸（../../etc/passwd）\n+3. 输出截断 —— 防止超大文件撑爆 token budget\n+4. LangChain StructuredTool —— 直接接入 LangGraph ReAct Agent\n+"""\n \n import re\n import logging'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 13,
        diff_text = '@@ -1,4 +1,15 @@\n-\n+"""\n+工具层：Critic 的 3 个核心工具\n+- read_file: 读取仓库文件（整个 clone 下来的仓库）\n+- grep: 正则搜索仓库代码\n+- get_diff_file: 获取 MR 中指定变更文件的 diff\n+\n+设计原则：\n+1. 工厂模式 —— 运行时注入 repo_manager 和 file_changes 依赖\n+2. 路径安全 —— 防止 LLM 构造路径逃逸（../../etc/passwd）\n+3. 输出截断 —— 防止超大文件撑爆 token budget\n+4. LangChain StructuredTool —— 直接接入 LangGraph ReAct Agent\n+"""\n \n import re\n import logging\n'
    ),
    FileChange(
        path = 'app/config.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 4,
                new_start = 1,
                new_lines = 8,
                content = '@@ -1,4 +1,8 @@\n-\n+"""\n+DevBot 配置管理\n+所有敏感信息通过环境变量注入，不硬编码。\n+面试点：12-Factor App 配置外置原则。\n+"""\n \n from pydantic_settings import BaseSettings\n from functools import lru_cache'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 6,
        diff_text = '@@ -1,4 +1,8 @@\n-\n+"""\n+DevBot 配置管理\n+所有敏感信息通过环境变量注入，不硬编码。\n+面试点：12-Factor App 配置外置原则。\n+"""\n \n from pydantic_settings import BaseSettings\n from functools import lru_cache\n'
    ),
    FileChange(
        path = 'app/main.py',
        language = 'python',
        hunks = [
            Hunk(
                old_start = 1,
                old_lines = 3,
                new_start = 1,
                new_lines = 7,
                content = '@@ -1,3 +1,7 @@\n+"""\n+DevBot — FastAPI 入口\n+接收 GitLab Webhook，异步触发 MR 评审流程。\n+"""\n \n import logging\n import sys'
            )
        ],
        is_new = False,
        is_deleted = False,
        is_renamed = False,
        changed_lines = 4,
        diff_text = '@@ -1,3 +1,7 @@\n+"""\n+DevBot — FastAPI 入口\n+接收 GitLab Webhook，异步触发 MR 评审流程。\n+"""\n \n import logging\n import sys\n'
    )
]

let initial_state = {
	'changes': [{
		'diff': '@@ -1,4 +1,12 @@\n+"""\n+GitLab API 客户端\n+封装 MR 评论、Commit Status、获取 diff 等操作。\n \n+GitLab API 特点（vs GitHub）：\n+- 项目用 ID 或 URL-encoded path 标识（如 group%2Fproject）\n+- 行级评论通过 Discussions API 实现\n+- Commit Status API 参数略有不同\n+"""\n \n import logging\n import httpx\n@@ -43,6 +51,10 @@ class GitLabClient:\n         创建行级评论（通过 Discussion API）。\n         GitLab 行级评论需要 position 对象，比 GitHub 复杂。\n         """\n+        if not new_line or new_line < 1:\n+            logger.warning(f"[GitLab] 行号无效({new_line})，跳过行级评论: {new_path}")\n+            return\n+\n         url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/discussions"\n         payload = {\n             "body": body,\n@@ -51,6 +63,7 @@ class GitLabClient:\n                 "head_sha": head_sha,\n                 "start_sha": start_sha,\n                 "position_type": "text",\n+                "old_path": new_path,\n                 "new_path": new_path,\n                 "new_line": new_line,\n             },\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/gitlab/client.py',
		'old_path': 'app/gitlab/client.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,4 +1,17 @@\n-\n+"""\n+GitLab Webhook 路由\n+接收 MR 事件，X-Gitlab-Token 校验，异步触发评审。\n+\n+完整流程：\n+  Webhook → 校验 → 过滤事件 → 异步触发 _run_review()\n+  _run_review():\n+    1. 获取 MR 详情（sha、branch、repo URL）\n+    2. 获取 MR diff（changes JSON）\n+    3. 设置 Commit Status = "running"\n+    4. 调用 LangGraph 审查图（run_review）\n+    5. 发布审查结果（摘要 + 行级评论）\n+    6. 设置 Commit Status = "success" / "failed"\n+"""\n import asyncio\n import logging\n \n@@ -68,7 +81,7 @@ async def _run_review(webhook_data: dict):\n \n     logger.info(f"[审查] ══ 开始 ══ Project #{project_id} MR !{mr_iid}")\n     logger.info(f"[审查] 分支: {source_branch} | head_sha: {head_sha[:12]}...")\n-    logger.debug(f"[审查] repo_url: {repo_url[:50]}...")\n+    logger.debug(f"[审查] repo_url: {repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:50]}...")\n \n     try:\n \n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/gitlab/webhook.py',
		'old_path': 'app/gitlab/webhook.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,4 +1,15 @@\n+"""\n+LangGraph 图构建器\n+将所有节点组装为完整的审查流水线。\n \n+图结构：\n+  prepare ──→ Send × 4 Critics（并行）──→ aggregate ──→ reflect ──→ report\n+\n+关键机制：\n+- Send API: 确定性扇出到 4 个 Critic（不是 LLM 决定启动几个，是工程逻辑决定）\n+- operator.add reducer: 并行 Critic 的结果自动合并到 critic_results 列表\n+- 异步执行: Critic 和 Reflector 是 async 节点（LLM 调用）\n+"""\n \n import logging\n from typing import Any\n@@ -160,7 +171,8 @@ async def run_review(\n \n     repo_manager = RepoManager()\n     try:\n-        logger.info(f"[RunReview] 开始 clone 仓库: {repo_url[:60]}... branch={branch}")\n+        safe_url = repo_url.split(\'@\')[-1] if \'@\' in repo_url else repo_url[:60]\n+        logger.info(f"[RunReview] 开始 clone 仓库: {safe_url} | branch={branch}")\n         await repo_manager.clone(repo_url, branch)\n         logger.info(f"[RunReview] 仓库已 clone 到: {repo_manager.clone_path}")\n \n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/graph/builder.py',
		'old_path': 'app/graph/builder.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,3 +1,15 @@\n+"""\n+LangGraph 节点实现\n+每个节点是图中的一个处理步骤。\n+\n+节点列表：\n+- prepare: Harness 层处理（解析 → 过滤 → 分组 → 规则匹配）\n+- run_critic: 运行单个 Critic ReAct Agent\n+- aggregate: 合并去重所有 Critic 的 findings\n+- reflect: Reflector 验证 critical/warning findings\n+- report: 计算风险分 + 生成输出\n+"""\n+\n \n import json\n import logging\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/graph/nodes.py',
		'old_path': 'app/graph/nodes.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,4 +1,12 @@\n-\n+"""\n+LangGraph 状态定义\n+State 是图中所有节点共享的数据结构，每个节点读取 + 修改 State。\n+\n+设计意图：\n+- 输入字段：Webhook 传入的原始数据\n+- 中间字段：各节点产出的中间结果\n+- 输出字段：最终审查报告\n+"""\n \n import operator\n from typing import Annotated, Any, Optional\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/graph/state.py',
		'old_path': 'app/graph/state.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,3 +1,45 @@\n+"""2\n+Diff 解析器\n+将 GitLab MR changes API 返回的 JSON 解析为结构化 FileChange 列表。\n+\n+GitLab 返回格式：\n+[\n+  {\n+    "old_path": "src/user.py",\n+    "new_path": "src/user.py",\n+    "diff": "--- a/src/user.py\\n+++ b/src/user.py\\n@@ -1,3 +1,4 @@\\n...",\n+    "new_file": false,\n+    "deleted_file": false,\n+    "renamed_file": false\n+  },\n+  ...\n+]\n+\n+\n+# 输入：GitLab API 返回的 JSON\n+changes = [\n+    {\n+        "new_path": "src/auth/login.py",\n+        "old_path": "src/auth/login.py",\n+        "diff": "@@ -10,4 +10,6 @@\\n def login(username, password):\\n-    user = User.query.filter_by(name=username).first()\\n+    user = User.query.filter_by(name=username)\\n+    if not user:\\n+        return None\\n     return generate_token(user)",\n+        "new_file": False,\n+        "deleted_file": False,\n+        "renamed_file": False,\n+    }\n+]\n+\n+# 输出：结构化 FileChange\n+FileChange(\n+    path="src/auth/login.py",\n+    language="python",\n+    changed_lines=4,          # 1行删除 + 3行新增\n+    is_new=False,\n+    is_deleted=False,\n+    hunks=[Hunk(old_start=10, old_lines=4, new_start=10, new_lines=6, content="...")],\n+    diff_text="@@ -10,4 +10,6 @@\\n def login(..."  # 原始文本保留\n+)\n+"""\n+\n import re\n import logging\n from dataclasses import dataclass, field\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/harness/diff_parser.py',
		'old_path': 'app/harness/diff_parser.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,3 +1,30 @@\n+"""3\n+文件过滤器\n+确定性规则过滤不需要审查的文件。\n+这是 Harness 层"必须做到的事"——不依赖 LLM 判断。\n+\n+过滤逻辑参考阿里 OCR：精确文件选择，确保不浪费 token 在垃圾文件上。\n+\n+\n+# 输入：4 个 FileChange\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=4),\n+    FileChange(path="package-lock.json", changed_lines=3000),\n+    FileChange(path="src/auth/logo.png", changed_lines=0, is_deleted=False),\n+    FileChange(path="old_helper.py", changed_lines=0, is_deleted=True),\n+]\n+\n+# 输出：只剩 1 个\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=4),\n+]\n+\n+# 被过滤的原因：\n+# package-lock.json → 命中 lock 文件正则\n+# logo.png → 命中图片后缀正则\n+# old_helper.py → is_deleted=True（删除的文件审查价值低）\n+"""\n+\n import re\n import logging\n from app.harness.diff_parser import FileChange\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/harness/file_filter.py',
		'old_path': 'app/harness/file_filter.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,3 +1,30 @@\n+"""4\n+文件分组器\n+将变更文件列表按行数阈值分为多个 bundle。\n+\n+核心规则（面试要能讲清楚）：\n+1. 文件是最小单位，永远不会被拆分\n+2. 单文件超过阈值 → 独占一个 bundle\n+3. 多个小文件打包到一起，直到接近阈值\n+4. 阈值默认 800 行（保证 LLM 注意力质量）\n+\n+\n+# 输入：过滤后的文件列表（假设剩 6 个文件）\n+[\n+    FileChange(path="src/auth/login.py", changed_lines=200),\n+    FileChange(path="src/auth/token.py", changed_lines=150),\n+    FileChange(path="src/api/routes.py", changed_lines=300),\n+    FileChange(path="src/models/user.py", changed_lines=100),\n+    FileChange(path="src/utils/helper.py", changed_lines=50),\n+    FileChange(path="src/legacy/old_module.py", changed_lines=900),  # 大文件！\n+]\n+\n+# 输出：3 个 Bundle（阈值 800 行）\n+Bundle 1: [src/legacy/old_module.py]           (900行，独占)\n+Bundle 2: [src/api/routes.py, src/auth/login.py, src/auth/token.py]  (650行)\n+Bundle 3: [src/models/user.py, src/utils/helper.py]                  (150行)\n+(打bundle主要是考虑成本因素，减少多次请求的token消耗)\n+"""\n \n import logging\n from dataclasses import dataclass, field\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/harness/file_grouper.py',
		'old_path': 'app/harness/file_grouper.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,7 +1,26 @@\n+"""1\n+仓库管理器\n+负责 git clone 到本地临时目录，审查结束后清理。\n+工具层（read_file/grep）操作的就是这里 clone 下来的本地文件。\n+\n+\n+输入：\n+  repo_url = "https://gitlab.com/team/project.git"\n+  branch = "feature/add-login"\n+\n+执行：\n+  git clone --depth=1 --single-branch --branch feature/add-login \\\n+      https://gitlab.com/team/project.git /tmp/devbot_repos/abc123/\n+\n+输出：\n+  clone_path = Path("/tmp/devbot_repos/abc123/")\n+  → 后续 read_file / grep 工具都在这个目录下操作\n+"""\n \n import asyncio\n import logging\n import shutil\n+import subprocess\n import tempfile\n from pathlib import Path\n \n@@ -33,6 +52,8 @@ class RepoManager:\n         base_dir.mkdir(parents=True, exist_ok=True)\n \n         self._clone_path = Path(tempfile.mkdtemp(dir=base_dir))\n+        # mkdtemp 会创建目录，但 git clone 要求目标不存在，先删掉\n+        shutil.rmtree(self._clone_path)\n         logger.info(f"[Repo] 开始 clone → {self._clone_path}")\n         logger.debug(f"[Repo] 命令: git clone --depth=1 --single-branch --branch {branch}")\n \n@@ -45,16 +66,18 @@ class RepoManager:\n             str(self._clone_path),\n         ]\n \n-        process = await asyncio.create_subprocess_exec(\n-            *cmd,\n-            stdout=asyncio.subprocess.PIPE,\n-            stderr=asyncio.subprocess.PIPE,\n+        # Windows 上 asyncio.create_subprocess_exec 不兼容 uvicorn 事件循环\n+        # 改用 run_in_executor + subprocess.run 保证跨平台兼容\n+        loop = asyncio.get_event_loop()\n+        result = await loop.run_in_executor(\n+            None,\n+            lambda: subprocess.run(cmd, capture_output=True, timeout=120),\n         )\n-        _, stderr = await process.communicate()\n \n-        if process.returncode != 0:\n-            logger.error(f"[Repo] clone 失败: {stderr.decode()[:200]}")\n-            raise RuntimeError(f"git clone failed: {stderr.decode()}")\n+        if result.returncode != 0:\n+            err_msg = result.stderr.decode(errors="replace")[:200]\n+            logger.error(f"[Repo] clone 失败: {err_msg}")\n+            raise RuntimeError(f"git clone failed: {err_msg}")\n \n         logger.info(f"[Repo] clone 完成: {self._clone_path}")\n         return self._clone_path\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/harness/repo_manager.py',
		'old_path': 'app/harness/repo_manager.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,3 +1,27 @@\n+"""5\n+规则匹配器\n+根据文件语言和路径，注入对应的审查规则到 Critic prompt 中。\n+\n+这是 Harness 层的"确定性规则注入"——\n+不让 LLM 自己决定关注什么规则，而是工程逻辑预先匹配好。\n+参考阿里 OCR 的模板引擎规则匹配思路（但简化为 Python dict）。\n+\n+\n+# 输入：Bundle 2 的文件列表\n+[\n+    FileChange(path="src/api/routes.py", language="python"),\n+    FileChange(path="src/auth/login.py", language="python"),\n+]\n+\n+# 输出：拼接到 Critic prompt 里的规则文本\n+\n+【本次审查需重点关注的规则】\n+  - 检查异常处理：是否有裸 except、是否吞掉了异常\n+  - 检查接口参数校验是否完整        ← 因为路径匹配了 /api/\n+  - 检查是否缺少类型注解（函数参数和返回值）\n+  - 检查资源管理：文件/连接是否使用 with 语句\n+  - 检查鉴权中间件是否生效          ← 因为路径匹配了 route\n+"""\n \n import logging\n from app.harness.diff_parser import FileChange\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/harness/rule_matcher.py',
		'old_path': 'app/harness/rule_matcher.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,3 +1,14 @@\n+"""\n+Prompt Registry\n+加载 YAML prompt 模板并填充运行时变量。\n+\n+设计意图：\n+- Prompt 外置为 YAML 文件，修改 prompt 不用改 Python 代码\n+- 统一加载接口，Critic/Reflector 通过名字获取 prompt\n+- 模板变量用 str.format() 填充（{diff_text}、{rules} 等）\n+"""\n+\n+\n from pathlib import Path\n from dataclasses import dataclass\n import logging\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/prompts/registry.py',
		'old_path': 'app/prompts/registry.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,4 +1,15 @@\n-\n+"""\n+工具层：Critic 的 3 个核心工具\n+- read_file: 读取仓库文件（整个 clone 下来的仓库）\n+- grep: 正则搜索仓库代码\n+- get_diff_file: 获取 MR 中指定变更文件的 diff\n+\n+设计原则：\n+1. 工厂模式 —— 运行时注入 repo_manager 和 file_changes 依赖\n+2. 路径安全 —— 防止 LLM 构造路径逃逸（../../etc/passwd）\n+3. 输出截断 —— 防止超大文件撑爆 token budget\n+4. LangChain StructuredTool —— 直接接入 LangGraph ReAct Agent\n+"""\n \n import re\n import logging\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/tools/code_tools.py',
		'old_path': 'app/tools/code_tools.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,4 +1,8 @@\n-\n+"""\n+DevBot 配置管理\n+所有敏感信息通过环境变量注入，不硬编码。\n+面试点：12-Factor App 配置外置原则。\n+"""\n \n from pydantic_settings import BaseSettings\n from functools import lru_cache\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/config.py',
		'old_path': 'app/config.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}, {
		'diff': '@@ -1,3 +1,7 @@\n+"""\n+DevBot — FastAPI 入口\n+接收 GitLab Webhook，异步触发 MR 评审流程。\n+"""\n \n import logging\n import sys\n',
		'collapsed': False,
		'too_large': False,
		'new_path': 'app/main.py',
		'old_path': 'app/main.py',
		'a_mode': '100644',
		'b_mode': '100644',
		'new_file': False,
		'renamed_file': False,
		'deleted_file': False,
		'generated_file': False
	}],
	'repo_url': 'https://oauth2:xX8Wi3VpitFJ86ua4-yDom86MQp1OjVpdXIK.01.1016g6l44@jihulab.com/liushijie_2000-group/devbot.git',
	'branch': 'master',
	'mr_iid': 5,
	'project_id': 356482
}