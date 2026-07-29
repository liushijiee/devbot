import re
import logging
from app.harness.diff_parser import FileChange

logger = logging.getLogger(__name__)

EXCLUDE_PATTERNS = [

    r".*package-lock\.json$",
    r".*yarn\.lock$",
    r".*pnpm-lock\.yaml$",
    r".*poetry\.lock$",
    r".*Pipfile\.lock$",
    r".*Gemfile\.lock$",
    r".*go\.sum$",

    r".*/dist/.*",
    r".*/build/.*",
    r".*/\.next/.*",
    r".*/node_modules/.*",
    r".*/__pycache__/.*",
    r".*\.pyc$",

    r".*/\.idea/.*",
    r".*/\.vscode/.*",
    r".*\.DS_Store$",

    r".*\.generated\..*",
    r".*\.g\.dart$",
    r".*_pb2\.py$",
    r".*_pb2_grpc\.py$",

    r".*/migrations/\d+_.*\.py$",

    r".*\.(png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$",
]

_EXCLUDE_RE = [re.compile(p, re.IGNORECASE) for p in EXCLUDE_PATTERNS]

def should_exclude(file: FileChange) -> bool:
    """判断单个文件是否应被过滤。"""

    if file.is_deleted:
        return True

    if file.is_renamed and file.changed_lines == 0:
        return True

    for pattern in _EXCLUDE_RE:
        if pattern.match(file.path):
            return True

    return False

def filter_files(files: list[FileChange]) -> list[FileChange]:
    """
    主入口：过滤无关文件，返回需要审查的文件列表。
    """
    kept = [f for f in files if not should_exclude(f)]
    excluded = [f for f in files if should_exclude(f)]

    logger.info(f"[FileFilter] 输入 {len(files)} 个文件 → 保留 {len(kept)} 个, 过滤 {len(excluded)} 个")
    for f in excluded:
        reason = "deleted" if f.is_deleted else ("renamed(no change)" if f.is_renamed else "pattern match")
        logger.debug(f"[FileFilter]   ✗ {f.path} ({reason})")
    for f in kept:
        logger.debug(f"[FileFilter]   ✓ {f.path}")

    return kept
