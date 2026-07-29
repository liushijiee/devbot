"""4
文件分组器
将变更文件列表按行数阈值分为多个 bundle。

核心规则（面试要能讲清楚）：
1. 文件是最小单位，永远不会被拆分
2. 单文件超过阈值 → 独占一个 bundle
3. 多个小文件打包到一起，直到接近阈值
4. 阈值默认 800 行（保证 LLM 注意力质量）


# 输入：过滤后的文件列表（假设剩 6 个文件）
[
    FileChange(path="src/auth/login.py", changed_lines=200),
    FileChange(path="src/auth/token.py", changed_lines=150),
    FileChange(path="src/api/routes.py", changed_lines=300),
    FileChange(path="src/models/user.py", changed_lines=100),
    FileChange(path="src/utils/helper.py", changed_lines=50),
    FileChange(path="src/legacy/old_module.py", changed_lines=900),  # 大文件！
]

# 输出：3 个 Bundle（阈值 800 行）
Bundle 1: [src/legacy/old_module.py]           (900行，独占)
Bundle 2: [src/api/routes.py, src/auth/login.py, src/auth/token.py]  (650行)
Bundle 3: [src/models/user.py, src/utils/helper.py]                  (150行)
(打bundle主要是考虑成本因素，减少多次请求的token消耗)
"""

import logging
from dataclasses import dataclass, field

from app.config import get_settings
from app.harness.diff_parser import FileChange

logger = logging.getLogger(__name__)

@dataclass
class Bundle:
    """一个审查批次，包含一个或多个文件。"""
    files: list[FileChange] = field(default_factory=list)
    total_lines: int = 0

    @property
    def diff_text(self) -> str:
        """拼接 bundle 内所有文件的 diff（直接喂给 Critic）。"""
        parts = []
        for f in self.files:
            parts.append(f"--- {f.path} ---")
            parts.append(f.diff_text)
        return "\n\n".join(parts)

    @property
    def file_paths(self) -> list[str]:
        """bundle 内所有文件路径。"""
        return [f.path for f in self.files]

def group_files(
    files: list[FileChange],
    max_lines: int | None = None,
) -> list[Bundle]:
    """
    主入口：将文件列表分组为 bundle 列表。

    策略：
    - 按变更行数降序排列（大文件优先处理）
    - 超阈值的文件独占 bundle
    - 小文件贪心打包
    """
    if max_lines is None:
        max_lines = get_settings().max_file_lines_per_bundle

    bundles: list[Bundle] = []
    current_files: list[FileChange] = []
    current_lines = 0

    sorted_files = sorted(files, key=lambda f: f.changed_lines, reverse=True)

    for file in sorted_files:

        if file.changed_lines > max_lines:
            bundles.append(Bundle(files=[file], total_lines=file.changed_lines))

        elif current_lines + file.changed_lines > max_lines:
            if current_files:
                bundles.append(Bundle(files=current_files, total_lines=current_lines))
            current_files = [file]
            current_lines = file.changed_lines

        else:
            current_files.append(file)
            current_lines += file.changed_lines

    if current_files:
        bundles.append(Bundle(files=current_files, total_lines=current_lines))

    logger.info(f"[FileGrouper] {len(files)} 个文件 → {len(bundles)} 个 bundle (max_lines={max_lines})")
    for i, b in enumerate(bundles, 1):
        logger.debug(f"[FileGrouper]   Bundle #{i}: {b.total_lines} 行, {len(b.files)} 个文件: {b.file_paths}")

    return bundles
