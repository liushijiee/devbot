
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
