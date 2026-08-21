"""
工具层：Critic 的 3 个核心工具
- read_file: 读取仓库文件（整个 clone 下来的仓库）
- grep: 正则搜索仓库代码
- get_diff_file: 获取 MR 中指定变更文件的 diff

设计原则：
1. 工厂模式 —— 运行时注入 repo_manager 和 file_changes 依赖
2. 路径安全 —— 防止 LLM 构造路径逃逸（../../etc/passwd）
3. 输出截断 —— 防止超大文件撑爆 token budget
4. LangChain StructuredTool —— 直接接入 LangGraph ReAct Agent
"""

import json
import re
import logging
import subprocess
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.harness.diff_parser import FileChange
from app.harness.repo_manager import RepoManager

logger = logging.getLogger(__name__)

MAX_READ_LINES = 500
MAX_GREP_RESULTS = 30
MAX_OUTPUT_CHARS = 8000

class ReadFileInput(BaseModel):
    path: str = Field(description="文件相对路径，如 src/auth/login.py")
    start_line: Optional[int] = Field(default=None, description="起始行号（1-based），不填则从头开始")
    end_line: Optional[int] = Field(default=None, description="结束行号（1-based），不填则到末尾")

class GrepInput(BaseModel):
    pattern: str = Field(description="正则表达式搜索模式，如 'def verify_password'")
    path: Optional[str] = Field(default=None, description="限定搜索目录，如 src/auth/，不填则搜全仓库")
    file_glob: Optional[str] = Field(default=None, description="文件名过滤，如 '*.py' 只搜 Python 文件")

class GetDiffFileInput(BaseModel):
    path: str = Field(description="变更文件路径，如 src/auth/login.py（必须是本次 MR 中变更的文件）")

def _safe_resolve(base: Path, relative: str) -> Path:
    """
    将相对路径解析为绝对路径，并校验不逃逸出 base 目录。
    防止 LLM 构造 '../../../etc/passwd' 之类的攻击路径。
    """

    resolved = (base / relative).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"路径越界: '{relative}' 逃逸出仓库目录")
    return resolved

def _truncate(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """截断过长输出，避免撑爆 LLM token。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... [输出截断，共 {len(text)} 字符，仅显示前 {max_chars} 字符]"

def _read_file(repo_manager: RepoManager, path: str,
               start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """读取仓库中的文件内容。"""
    try:
        file_path = _safe_resolve(repo_manager.clone_path, path)
    except ValueError as e:
        return f"[错误] {e}"

    if not file_path.exists():
        logger.debug(f"[Tool:read_file] ✗ 不存在: {path}")
        return f"[错误] 文件不存在: {path}"
    if not file_path.is_file():
        logger.debug(f"[Tool:read_file] ✗ 不是文件: {path}")
        return f"[错误] 不是文件: {path}"

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[错误] 读取失败: {e}"

    lines = content.splitlines()
    total = len(lines)

    start = (start_line or 1) - 1
    end = end_line or total
    start = max(0, start)
    end = min(total, end)

    if end - start > MAX_READ_LINES:
        end = start + MAX_READ_LINES
        truncated_note = f"\n[注意: 文件共 {total} 行，本次仅显示第 {start+1}-{end} 行]"
    else:
        truncated_note = ""

    selected = lines[start:end]

    numbered = [f"{start + i + 1:4d} | {line}" for i, line in enumerate(selected)]

    header = f"文件: {path} (共 {total} 行，显示 {start+1}-{end})\n{'─' * 40}\n"
    result = _truncate(header + "\n".join(numbered) + truncated_note)
    logger.info(f"[Tool:read_file] {path} 行{start+1}-{end}/{total} → {len(result)} 字符")
    return result

def _grep(repo_manager: RepoManager, pattern: str,
          path: Optional[str] = None, file_glob: Optional[str] = None) -> str:
    """在仓库中正则搜索代码。"""
    base = repo_manager.clone_path

    search_dir = base
    if path:
        try:
            search_dir = _safe_resolve(base, path)
        except ValueError as e:
            return f"[错误] {e}"
        if not search_dir.exists():
            return f"[错误] 目录不存在: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"[错误] 正则表达式无效: {e}"

    results = []
    glob_pattern = file_glob or "*"

    try:
        files = search_dir.rglob(glob_pattern) if search_dir.is_dir() else [search_dir]
        for f in files:
            if not f.is_file():
                continue

            if ".git" in f.parts:
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for i, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    rel_path = f.relative_to(base)
                    results.append(f"{rel_path}:{i}: {line.strip()}")
                    if len(results) >= MAX_GREP_RESULTS:
                        break
            if len(results) >= MAX_GREP_RESULTS:
                break
    except Exception as e:
        return f"[错误] 搜索失败: {e}"

    if not results:
        logger.info(f"[Tool:grep] /{pattern}/ → 0 匹配")
        return f"未找到匹配 '{pattern}' 的结果"

    header = f"搜索 '{pattern}' → {len(results)} 条匹配"
    if len(results) >= MAX_GREP_RESULTS:
        header += f"（已达上限 {MAX_GREP_RESULTS}）"
    header += f"\n{'─' * 40}\n"

    logger.info(f"[Tool:grep] /{pattern}/ → {len(results)} 匹配")
    return _truncate(header + "\n".join(results))

def _get_diff_file(file_changes: list[FileChange], path: str) -> str:
    """获取本次 MR 中指定变更文件的 diff。"""

    for fc in file_changes:
        if fc.path == path or fc.path.endswith("/" + path) or path.endswith("/" + fc.path):
            logger.info(f"[Tool:get_diff_file] {fc.path} → {len(fc.diff_text)} 字符")
            header = (
                f"文件: {fc.path}\n"
                f"语言: {fc.language} | 变更行数: {fc.changed_lines} | "
                f"新文件: {fc.is_new} | 删除: {fc.is_deleted}\n"
                f"{'─' * 40}\n"
            )
            return _truncate(header + fc.diff_text)

    logger.debug(f"[Tool:get_diff_file] ✗ 未找到: {path}")
    available = [fc.path for fc in file_changes]
    return (
        f"[错误] '{path}' 不在本次 MR 变更文件中。\n"
        f"本次 MR 变更的文件列表:\n" +
        "\n".join(f"  - {p}" for p in available)
    )

def create_tools(repo_manager: RepoManager, file_changes: list[FileChange]) -> list[StructuredTool]:
    """
    创建 Critic 可用的 3 个工具实例。

    参数:
        repo_manager: 已 clone 完毕的仓库管理器（提供 clone_path）
        file_changes: 本次 MR 的全部变更文件列表（供 get_diff_file 查询）

    返回:
        [read_file_tool, grep_tool, get_diff_file_tool]

    去重熔断：每次调用 create_tools 生成独立的 call_cache，
    生命周期 = 单个 Agent 的一次 ainvoke（Critic/Reflector 之间天然隔离）。
    相同（工具名+参数）的调用第二次出现时不再真实执行，
    直接返回首次结果 + 收敛提示（相同只读调用不可能返回新信息）。
    """
    call_cache: dict[str, tuple[int, str]] = {}  # key → (调用次数, 首次执行结果)

    def _guarded(name: str, key_args: dict, func) -> str:
        """工具执行入口：拦截完全重复的调用。"""
        key = f"{name}:{json.dumps(key_args, sort_keys=True, ensure_ascii=False)}"
        if key in call_cache:
            count, first_result = call_cache[key]
            call_cache[key] = (count + 1, first_result)
            logger.warning(f"[Tool:{name}] 拦截第 {count + 1} 次重复调用: {key}")
            return (
                f"[重复调用拦截] 你已用完全相同的参数调用过 {name}，相同调用不可能返回新信息。\n"
                f"该调用的结果如下（与首次相同）：\n{first_result}\n\n"
                f"决策规则：\n"
                f"- 若上述信息已足够 → 立即输出最终结论，不要追加调查\n"
                f"- 若仍需其他信息 → 必须更换参数发起新查询（不同文件/不同行区间/不同pattern）"
            )
        result = func()
        call_cache[key] = (1, result)
        return result

    read_file_tool = StructuredTool.from_function(
        func=lambda path, start_line=None, end_line=None: _guarded(
            "read_file",
            {"path": path, "start_line": start_line, "end_line": end_line},
            lambda: _read_file(repo_manager, path, start_line, end_line),
        ),
        name="read_file",
        description=(
            "读取仓库中指定文件的内容。可指定行范围。"
            "用于查看函数完整实现、类定义、配置文件等。"
            "路径是相对于仓库根目录的相对路径。"
        ),
        args_schema=ReadFileInput,
    )

    grep_tool = StructuredTool.from_function(
        func=lambda pattern, path=None, file_glob=None: _guarded(
            "grep",
            {"pattern": pattern, "path": path, "file_glob": file_glob},
            lambda: _grep(repo_manager, pattern, path, file_glob),
        ),
        name="grep",
        description=(
            "在仓库代码中进行正则表达式搜索。"
            "用于查找函数调用方、变量引用、配置项使用位置等。"
            "返回匹配的文件路径、行号和行内容。"
        ),
        args_schema=GrepInput,
    )

    get_diff_file_tool = StructuredTool.from_function(
        func=lambda path: _guarded(
            "get_diff_file",
            {"path": path},
            lambda: _get_diff_file(file_changes, path),
        ),
        name="get_diff_file",
        description=(
            "获取本次 MR 中指定变更文件的完整 diff。"
            "仅能查询本次 MR 实际变更的文件。"
            "用于查看其他变更文件的修改内容（跨 bundle 调查）。"
        ),
        args_schema=GetDiffFileInput,
    )

    logger.info(f"[Tools] 创建 3 个工具 (read_file, grep, get_diff_file) | 仓库: {repo_manager.clone_path}")
    return [read_file_tool, grep_tool, get_diff_file_tool]
