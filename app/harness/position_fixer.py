"""
行号定位模块（确定性 Positioning）

核心设计：LLM 不输出行号，而是输出 existing_code（代码片段），
由本模块通过确定性文本匹配计算出行号。

三层递进式定位策略（参考阿里 OCR）：
1. Hunk-based 文本匹配：用 existing_code 在 diff 新增行中做归一化匹配
2. Snippet 回退：从 description/suggestion 中提取代码片段匹配
3. 保留原样：匹配失败时保留原始状态，交由 GitLab 降级兜底

核心原则：
- 行号是工程问题，不是语言问题 → 用文本匹配而非 LLM 来定位
- 定位失败时保留 finding，绝不丢弃或降低可信度
- 只计算行号，不评判结论对错（那是 Reflector 的职责）
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def fix_positions(findings: list[dict], diff_text: str) -> list[dict]:
    """
    对 findings 列表做确定性行号定位。

    参数:
        findings: _parse_findings 输出的 Finding 列表
        diff_text: 当前 bundle 的完整 diff 文本（可能含多文件）

    返回:
        定位后的 findings（计算并设置 line 字段）
    """
    if not findings or not diff_text:
        return findings

    line_map = _parse_diff_lines(diff_text)
    if not line_map:
        return findings

    positioned_count = 0
    for finding in findings:
        file_path = finding.get("file", "")

        # 找到该文件在 diff 中的行映射
        file_lines = _match_file(file_path, line_map)
        if not file_lines:
            # 文件不在 diff 中，无法定位
            _cleanup_line(finding)
            continue

        # ── 第一层：existing_code 匹配（主策略）──
        existing_code = finding.get("existing_code", "")
        if existing_code:
            match_result = _match_code_in_diff(existing_code, file_lines)
            if match_result:
                matched_line, line_info = match_result
                finding["line"] = matched_line
                # 上下文行需要 old_line 才能在 GitLab 上定位
                if line_info["type"] == "context" and line_info["old_line"]:
                    finding["old_line"] = line_info["old_line"]
                positioned_count += 1
                logger.debug(
                    f"[PositionFixer] {file_path}: existing_code → 行 {matched_line} ({line_info['type']})"
                )
                continue

        # ── 第二层：从描述中提取 snippet 匹配 ──
        snippets = _extract_snippets(finding)
        if snippets:
            match_result = _find_best_match(snippets, file_lines)
            if match_result:
                matched_line, line_info = match_result
                finding["line"] = matched_line
                if line_info["type"] == "context" and line_info["old_line"]:
                    finding["old_line"] = line_info["old_line"]
                positioned_count += 1
                logger.debug(
                    f"[PositionFixer] {file_path}: snippet → 行 {matched_line} ({line_info['type']})"
                )
                continue

        # ── 第三层：都匹配不到，保留原始 line（如果有）或清除 ──
        # 如果 LLM 意外给了 line 且在 diff 有效范围内，保留
        original_line = finding.get("line")
        if original_line and isinstance(original_line, int) and original_line in file_lines:
            line_info = file_lines[original_line]
            if line_info["type"] == "context" and line_info["old_line"]:
                finding["old_line"] = line_info["old_line"]
            positioned_count += 1
            continue

        # 无法定位：清除无效 line，交由 GitLab 降级兜底
        _cleanup_line(finding)
        logger.debug(
            f"[PositionFixer] {file_path}: 无法定位，保留为文件级评论"
        )

    if positioned_count:
        logger.info(
            f"[PositionFixer] 成功定位 {positioned_count}/{len(findings)} 个 finding"
        )

    return findings


def _cleanup_line(finding: dict) -> None:
    """清除无效的行号，避免下游报错。"""
    line = finding.get("line")
    if line is not None and (not isinstance(line, int) or line < 1):
        finding.pop("line", None)


def _parse_diff_lines(diff_text: str) -> dict[str, dict[int, dict]]:
    """
    解析 unified diff，返回每个文件的行映射（含行类型信息）。

    返回: {
        "app/graph/nodes.py": {
            53: {"content": "    diff_text = ...", "type": "added", "old_line": None},
            54: {"content": "    return ...", "type": "context", "old_line": 50},
        },
        ...
    }

    行类型：
    - "added": '+' 新增行，只需 new_line
    - "context": ' ' 上下文行，需要 old_line + new_line

    行号计算规则：
    - 从 @@ -old_start,old_count +new_start,new_count @@ 中取两个起始行号
    - ' ' 上下文行 → old_line+1, new_line+1
    - '+' 新增行 → new_line+1（old_line 不变）
    - '-' 删除行 → old_line+1（new_line 不变）
    """
    result: dict[str, dict[int, dict]] = {}
    current_file = ""
    new_line = 0
    old_line = 0

    for line in diff_text.split("\n"):
        # 处理 bundle.diff_text 的分隔符: "--- path ---"
        separator_match = re.match(r"^--- (.+?) ---$", line)
        if separator_match:
            current_file = separator_match.group(1)
            if current_file not in result:
                result[current_file] = {}
            new_line = 0
            old_line = 0
            continue

        # 标准 unified diff 文件头：--- a/path
        if line.startswith("--- "):
            continue

        # 标准 unified diff 文件头：+++ b/path
        if line.startswith("+++ "):
            path = line[4:]
            if path.startswith("b/"):
                path = path[2:]
            current_file = path
            if current_file not in result:
                result[current_file] = {}
            new_line = 0
            old_line = 0
            continue

        # Hunk header: @@ -old_start,old_count +new_start,new_count @@
        hunk_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            old_line = int(hunk_match.group(1))
            new_line = int(hunk_match.group(2))
            continue

        if not current_file or new_line == 0:
            continue

        # Diff 内容行
        if line.startswith("+"):
            content = line[1:]
            result[current_file][new_line] = {
                "content": content, "type": "added", "old_line": None
            }
            new_line += 1
        elif line.startswith("-"):
            # 删除行：只推进 old_line，不记录（新文件中不存在）
            old_line += 1
        else:
            # 上下文行（以空格开头）或空行
            content = line[1:] if line.startswith(" ") else line
            result[current_file][new_line] = {
                "content": content, "type": "context", "old_line": old_line
            }
            new_line += 1
            old_line += 1

    return result


def _match_file(file_path: str, line_map: dict[str, dict[int, dict]]) -> dict[int, dict] | None:
    """模糊匹配文件路径。"""
    if not file_path:
        return None

    if file_path in line_map:
        return line_map[file_path]

    for diff_path, lines in line_map.items():
        if diff_path.endswith(file_path) or file_path.endswith(diff_path):
            return lines

    target_name = file_path.split("/")[-1]
    for diff_path, lines in line_map.items():
        if diff_path.split("/")[-1] == target_name:
            return lines

    return None


def _normalize(text: str) -> str:
    """归一化文本：去除所有空白字符，用于宽松匹配。"""
    return re.sub(r"\s+", "", text)


def _match_code_in_diff(existing_code: str, file_lines: dict[int, dict]) -> tuple[int, dict] | None:
    """
    第一层：Hunk-based 文本匹配。
    用 LLM 输出的 existing_code 在 diff 行中定位。

    返回: (line_no, line_info) 或 None
    """
    code = existing_code.strip()
    if not code:
        return None

    # 如果 existing_code 是多行的，取第一行做匹配
    code_lines = code.split("\n")
    primary_line = code_lines[0].strip()

    # 策略1：精确匹配（strip 后）
    for line_no, info in file_lines.items():
        if info["content"].strip() == primary_line:
            return line_no, info

    # 策略2：归一化匹配
    primary_norm = _normalize(primary_line)
    if len(primary_norm) >= 3:
        for line_no, info in file_lines.items():
            if _normalize(info["content"]) == primary_norm:
                return line_no, info

    # 策略3：子串匹配（双向）
    if len(primary_line) >= 6:
        for line_no, info in file_lines.items():
            content_stripped = info["content"].strip()
            if primary_line in content_stripped or content_stripped in primary_line:
                return line_no, info

    # 策略4：如果 existing_code 是多行，尝试匹配第二行
    if len(code_lines) > 1:
        second_line = code_lines[1].strip()
        if len(second_line) >= 4:
            for line_no, info in file_lines.items():
                if info["content"].strip() == second_line:
                    return line_no, info
            second_norm = _normalize(second_line)
            for line_no, info in file_lines.items():
                if _normalize(info["content"]) == second_norm:
                    return line_no, info

    return None


def _extract_snippets(finding: dict) -> list[str]:
    """
    第二层回退：从 finding 的 description/suggestion/title 中提取代码片段。
    """
    snippets = []
    desc = finding.get("description", "")
    suggestion = finding.get("suggestion", "")
    title = finding.get("title", "")
    text = f"{desc} {suggestion} {title}"

    # 反引号中的代码
    backtick_matches = re.findall(r"`([^`]+)`", text)
    for match in backtick_matches:
        if len(match) >= 4 and any(c in match for c in "=().[]_:"):
            snippets.append(match)

    # 代码模式（函数调用、赋值、下标访问等）
    code_patterns = re.findall(
        r'[\w.]+\([^)]*\)|[\w.]+\[[^\]]*\]|\w+\s*=\s*[\w."\']+',
        text
    )
    for pattern in code_patterns:
        if len(pattern) >= 5 and pattern not in snippets:
            snippets.append(pattern)

    return snippets


def _find_best_match(snippets: list[str], file_lines: dict[int, dict]) -> tuple[int, dict] | None:
    """在文件行映射中查找 snippet 的最佳匹配。返回 (line_no, line_info) 或 None。"""
    # 精确匹配
    for snippet in snippets:
        snippet_stripped = snippet.strip()
        if len(snippet_stripped) < 4:
            continue
        for line_no, info in file_lines.items():
            if info["content"].strip() == snippet_stripped:
                return line_no, info

    # 归一化匹配
    for snippet in snippets:
        snippet_norm = _normalize(snippet)
        if len(snippet_norm) < 5:
            continue
        for line_no, info in file_lines.items():
            if _normalize(info["content"]) == snippet_norm:
                return line_no, info

    # 子串匹配
    for snippet in snippets:
        snippet_stripped = snippet.strip()
        if len(snippet_stripped) < 6:
            continue
        for line_no, info in file_lines.items():
            if snippet_stripped in info["content"]:
                return line_no, info

    return None
