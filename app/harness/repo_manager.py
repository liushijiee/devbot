
import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

class RepoManager:
    """管理仓库的 clone 生命周期。"""

    def __init__(self):
        self._clone_path: Path | None = None

    @property
    def clone_path(self) -> Path:
        """当前 clone 的本地路径，工具层依赖此路径。"""
        if self._clone_path is None:
            raise RuntimeError("Repo not cloned yet. Call clone() first.")
        return self._clone_path

    async def clone(self, repo_url: str, branch: str) -> Path:
        """
        浅克隆仓库到临时目录。
        --depth=1：只拉最新一个 commit，节省时间和磁盘。
        --single-branch：只拉指定分支。
        """
        settings = get_settings()
        base_dir = Path(settings.repo_clone_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        self._clone_path = Path(tempfile.mkdtemp(dir=base_dir))
        logger.info(f"[Repo] 开始 clone → {self._clone_path}")
        logger.debug(f"[Repo] 命令: git clone --depth=1 --single-branch --branch {branch}")

        cmd = [
            "git", "clone",
            "--depth=1",
            "--single-branch",
            "--branch", branch,
            repo_url,
            str(self._clone_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"[Repo] clone 失败: {stderr.decode()[:200]}")
            raise RuntimeError(f"git clone failed: {stderr.decode()}")

        logger.info(f"[Repo] clone 完成: {self._clone_path}")
        return self._clone_path

    def cleanup(self):
        """审查结束后删除临时 clone 目录。"""
        if self._clone_path and self._clone_path.exists():
            logger.debug(f"[Repo] 清理临时目录: {self._clone_path}")
            shutil.rmtree(self._clone_path, ignore_errors=True)
            self._clone_path = None
