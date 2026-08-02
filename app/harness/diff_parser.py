"""2
Diff 解析器
将 GitLab MR changes API 返回的 JSON 解析为结构化 FileChange 列表。

GitLab 返回格式：
[
  {
    "old_path": "src/user.py",
    "new_path": "src/user.py",
    "diff": "--- a/src/user.py\n+++ b/src/user.py\n@@ -1,3 +1,4 @@\n...",
    "new_file": false,
    "deleted_file": false,
    "renamed_file": false
  },
  ...
]


# 输入：GitLab API 返回的 JSON
changes = [
    {
        "new_path": "src/auth/login.py",
        "old_path": "src/auth/login.py",
        "diff": "@@ -10,4 +10,6 @@\n def login(username, password):\n-    user = User.query.filter_by(name=username).first()\n+    user = User.query.filter_by(name=username)\n+    if not user:\n+        return None\n     return generate_token(user)",
        "new_file": False,
        "deleted_file": False,
        "renamed_file": False,
    }
]

# 输出：结构化 FileChange
FileChange(
    path="src/auth/login.py",
    language="python",
    changed_lines=4,          # 1行删除 + 3行新增
    is_new=False,
    is_deleted=False,
    hunks=[Hunk(old_start=10, old_lines=4, new_start=10, new_lines=6, content="...")],
    diff_text="@@ -10,4 +10,6 @@\n def login(..."  # 原始文本保留
)
"""

import re
import logging
from dataclasses import dataclass, field
from app.graph.tracer import trace_node

logger = logging.getLogger(__name__)

@dataclass
class Hunk:
    """一个 diff hunk（一段连续变更）。"""
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    content: str

@dataclass
class FileChange:
    """一个变更文件的结构化表示。"""
    path: str
    language: str
    hunks: list[Hunk] = field(default_factory=list)
    is_new: bool = False
    is_deleted: bool = False
    is_renamed: bool = False
    changed_lines: int = 0
    diff_text: str = ""

EXTENSION_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".cs": "csharp",
    ".vue": "vue",
    ".sql": "sql",
    ".sh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}

HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)

def detect_language(path: str) -> str:
    """根据文件后缀推断语言。"""
    for ext, lang in EXTENSION_LANGUAGE.items():
        if path.endswith(ext):
            return lang
    return "unknown"

def count_changed_lines(diff_text: str) -> int:
    """统计 diff 中新增(+)和删除(-)行的总数。"""
    count = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            count += 1
        elif line.startswith("-") and not line.startswith("---"):
            count += 1
    return count

def parse_hunks(diff_text: str) -> list[Hunk]:
    """将 unified diff 文本解析为 Hunk 列表。"""
    hunks = []
    current_hunk: Hunk | None = None
    content_lines: list[str] = []

    for line in diff_text.splitlines():
        match = HUNK_HEADER_RE.match(line)
        if match:

            if current_hunk:
                current_hunk.content = "\n".join(content_lines)
                hunks.append(current_hunk)

            current_hunk = Hunk(
                old_start=int(match.group(1)),
                old_lines=int(match.group(2) or 1),
                new_start=int(match.group(3)),
                new_lines=int(match.group(4) or 1),
                content="",
            )
            content_lines = [line]
        elif current_hunk:
            content_lines.append(line)

    if current_hunk:
        current_hunk.content = "\n".join(content_lines)
        hunks.append(current_hunk)
    # logger.info(f"[DiffParser] 解析 diff 完成: {hunks}")
    return hunks

@trace_node("1. parse_gitlab_changes")
def parse_gitlab_changes(changes: list[dict]) -> list[FileChange]:
    """
    主入口：将 GitLab API 返回的 changes 列表解析为 FileChange 列表。
    """
    logger.info(f"[DiffParser] 开始解析 {len(changes)} 个原始变更")
    result = []
    for item in changes:
        path = item.get("new_path", item.get("old_path", ""))
        diff_text = item.get("diff", "")

        file_change = FileChange(
            path=path,
            language=detect_language(path),
            hunks=parse_hunks(diff_text),
            is_new=item.get("new_file", False),
            is_deleted=item.get("deleted_file", False),
            is_renamed=item.get("renamed_file", False),
            changed_lines=count_changed_lines(diff_text),
            diff_text=diff_text,
        )
        result.append(file_change)
        logger.debug(
            f"[DiffParser]   {path} | {file_change.language} | "
            f"+/- {file_change.changed_lines} 行 | hunks={len(file_change.hunks)} | "
            f"new={file_change.is_new} del={file_change.is_deleted}"
        )

    logger.info(f"[DiffParser] 解析完成: {len(result)} 个 FileChange")
    # logger.info(f"parse_gitlab_changes result: {result}")
    return result
