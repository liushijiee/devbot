"""5
行号校正模块（确定性 Positioning）
Critic（LLM）从 diff 文本推算行号经常偏移，本模块在 findings 解析后做确定性校正。

核心原则：
- 行号是工程问题，不是语言问题 → 用文本匹配而非 LLM 来定位
- 校正失败时保留原始行号，绝不丢弃 finding 或降低可信度
- 只修正行号，不评判结论对错（那是 Reflector 的职责）

校正策略：
1. 验证原始行号是否在 diff 有效行内 → 有效则不动
2. 无效时，从 finding 描述中提取代码片段做匹配
3. 匹配失败时，找最近的有效行兜底
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def fix_positions(findings: list[dict], diff_text: str) -> list[dict]:
    """
    对 findings 列表做确定性行号校正。

    参数:
        findings: _parse_findings 输出的 Finding 列表
        diff_text: 当前 bundle 的完整 diff 文本（可能含多文件）

    返回:
        校正后的 findings（原地修改 line 字段）
    """
    if not findings or not diff_text:
        return findings

    line_map = _parse_diff_lines(diff_text)
    if not line_map:
        return findings

    fixed_count = 0
    for finding in findings:
        file_path = finding.get("file", "")
        original_line = finding.get("line", 0)

        # 行号为空或无效时跳过校正
        if not original_line or not isinstance(original_line, int) or original_line < 1:
            continue

        # 找到该文件在 diff 中的行映射
        file_lines = _match_file(file_path, line_map)
        if not file_lines:
            continue

        # ── 第一步：验证原始行号是否有效 ──
        if original_line in file_lines:
            # 行号在 diff 有效行内，不需要修正
            continue

        # ── 第二步：原始行号无效，尝试 snippet 匹配 ──
        snippets = _extract_snippets(finding)
        matched_line = _find_best_match(snippets, file_lines) if snippets else None

        if matched_line:
            logger.debug(
                f"[PositionFixer] {file_path}: 行号 {original_line} → {matched_line} (snippet匹配)"
            )
            finding["line"] = matched_line
            fixed_count += 1
            continue

        # ── 第三步：snippet 也匹配不到，找最近的有效行 ──
        closest = _find_closest_line(original_line, file_lines)
        if closest and closest != original_line:
            logger.debug(
                f"[PositionFixer] {file_path}: 行号 {original_line} → {closest} (最近有效行)"
            )
            finding["line"] = closest
            fixed_count += 1

    if fixed_count:
        logger.info(f"[PositionFixer] 校正了 {fixed_count}/{len(findings)} 个 finding 的行号")

    return findings


def _parse_diff_lines(diff_text: str) -> dict[str, dict[int, str]]:
    """
    解析 unified diff，返回每个文件的新增行/上下文行映射。

    返回: {
        "app/graph/nodes.py": {53: "    diff_text = state.get(...)", 54: "...", ...},
        ...
    }

    行号计算规则：
    - 从 @@ -x,y +start,count @@ 中取 new_start 作为起始行号
    - ' ' 上下文行 → 行号+1（存在于新文件）
    - '+' 新增行 → 记录，行号+1
    - '-' 删除行 → 不计数（不存在于新文件）
    """
    result: dict[str, dict[int, str]] = {}
    current_file = ""
    current_line = 0

    for line in diff_text.split("\n"):
        # 处理 bundle.diff_text 的分隔符: "--- path ---"（必须在通用 --- 判断之前）
        separator_match = re.match(r"^--- (.+?) ---$", line)
        if separator_match:
            current_file = separator_match.group(1)
            if current_file not in result:
                result[current_file] = {}
            current_line = 0  # 重置，等待 hunk header
            continue

        # 标准 unified diff 文件头：--- a/path（跳过，用 +++ 行确定文件）
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
            current_line = 0
            continue

        # Hunk header
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if not current_file or current_line == 0:
            continue

        # Diff 内容行
        if line.startswith("+"):
            content = line[1:]
            result[current_file][current_line] = content
            current_line += 1
        elif line.startswith("-"):
            # 删除行：不存在于新文件，不计数
            pass
        else:
            # 上下文行（以空格开头）或空行
            content = line[1:] if line.startswith(" ") else line
            result[current_file][current_line] = content
            current_line += 1

    return result


def _match_file(file_path: str, line_map: dict[str, dict[int, str]]) -> dict[int, str] | None:
    """
    模糊匹配文件路径。
    finding 中的 file 可能是完整路径或相对路径，diff 中的也是。
    """
    if not file_path:
        return None

    # 精确匹配
    if file_path in line_map:
        return line_map[file_path]

    # 尾部匹配（处理 ./src/a.py vs src/a.py 等差异）
    for diff_path, lines in line_map.items():
        if diff_path.endswith(file_path) or file_path.endswith(diff_path):
            return lines

    # 文件名匹配（最后手段）
    target_name = file_path.split("/")[-1]
    for diff_path, lines in line_map.items():
        if diff_path.split("/")[-1] == target_name:
            return lines

    return None


def _extract_snippets(finding: dict) -> list[str]:
    """
    从 finding 中提取候选代码片段，用于在 diff 中定位。

    提取策略（由强到弱）：
    1. 反引号包裹的代码（`code`）
    2. 看起来像代码的片段（含赋值、调用、下标等特征）
    3. 从 title 中提取函数名/变量名作为关键词
    """
    snippets = []
    desc = finding.get("description", "")
    suggestion = finding.get("suggestion", "")
    title = finding.get("title", "")
    text = f"{desc} {suggestion} {title}"

    # 策略1：反引号中的代码
    backtick_matches = re.findall(r"`([^`]+)`", text)
    for match in backtick_matches:
        # 过滤太短的和纯自然语言
        if len(match) >= 4 and any(c in match for c in "=().[]_:"):
            snippets.append(match)

    # 策略2：从描述中提取像代码的片段
    # 匹配常见的代码模式：func(...), x.y, x = y, x["key"]
    code_patterns = re.findall(
        r'[\w.]+\([^)]*\)|[\w.]+\[[^\]]*\]|\w+\s*=\s*[\w."\']+',
        text
    )
    for pattern in code_patterns:
        if len(pattern) >= 5 and pattern not in snippets:
            snippets.append(pattern)

    # 策略3：从 title 中提取标识符（函数名、变量名）
    # 例如 title="prepare 函数缺少类型注解" → 提取 "prepare"
    identifiers = re.findall(r'\b[a-zA-Z_]\w{2,}\b', title)
    # 过滤常见英文单词
    stop_words = {"the", "and", "for", "with", "from", "this", "that", "not", "are", "was"}
    for ident in identifiers:
        if ident.lower() not in stop_words and len(ident) >= 4:
            if ident not in snippets:
                snippets.append(ident)

    return snippets


def _find_best_match(snippets: list[str], file_lines: dict[int, str]) -> int | None:
    """
    在文件行映射中查找最佳匹配行号。

    匹配策略：
    1. 精确匹配（strip 后完全相同）
    2. 归一化匹配（去除所有空格后相同）
    3. 子串匹配（snippet 是某行的子串）
    """
    # 策略1：精确匹配（strip 后）
    for snippet in snippets:
        snippet_stripped = snippet.strip()
        if len(snippet_stripped) < 4:
            continue
        for line_no, content in file_lines.items():
            if content.strip() == snippet_stripped:
                return line_no

    # 策略2：归一化匹配（去除所有空格）
    for snippet in snippets:
        snippet_norm = re.sub(r"\s+", "", snippet)
        if len(snippet_norm) < 5:
            continue
        for line_no, content in file_lines.items():
            content_norm = re.sub(r"\s+", "", content)
            if content_norm == snippet_norm:
                return line_no

    # 策略3：子串匹配（snippet 出现在某行中）
    for snippet in snippets:
        snippet_stripped = snippet.strip()
        if len(snippet_stripped) < 6:
            continue
        for line_no, content in file_lines.items():
            if snippet_stripped in content:
                return line_no

    return None


def _find_closest_line(target_line: int, file_lines: dict[int, str]) -> int | None:
    """
    找距离 target_line 最近的有效行号。
    用于 snippet 匹配失败时的兜底：至少把行号拉回 diff 覆盖范围内。
    """
    if not file_lines:
        return None

    valid_lines = sorted(file_lines.keys())

    # 找最近的
    closest = min(valid_lines, key=lambda x: abs(x - target_line))

    # 如果偏差超过 5 行，说明 finding 指向的代码根本不在 diff 中，不修正
    if abs(closest - target_line) > 5:
        return None

    return closest
