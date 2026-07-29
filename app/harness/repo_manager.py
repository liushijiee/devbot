"""1
仓库管理器
负责 git clone 到本地临时目录，审查结束后清理。
工具层（read_file/grep）操作的就是这里 clone 下来的本地文件。


输入：
  repo_url = "https://gitlab.com/team/project.git"
  branch = "feature/add-login"

执行：
  git clone --depth=1 --single-branch --branch feature/add-login \
      https://gitlab.com/team/project.git /tmp/devbot_repos/abc123/

输出：
  clone_path = Path("/tmp/devbot_repos/abc123/")
  → 后续 read_file / grep 工具都在这个目录下操作
"""

import asyncio
import logging
import shutil
import subprocess
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
        # mkdtemp 会创建目录，但 git clone 要求目标不存在，先删掉
        shutil.rmtree(self._clone_path)
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

        # Windows 上 asyncio.create_subprocess_exec 不兼容 uvicorn 事件循环
        # 改用 run_in_executor + subprocess.run 保证跨平台兼容
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, timeout=120),
        )

        if result.returncode != 0:
            err_msg = result.stderr.decode(errors="replace")[:200]
            logger.error(f"[Repo] clone 失败: {err_msg}")
            raise RuntimeError(f"git clone failed: {err_msg}")

        logger.info(f"[Repo] clone 完成: {self._clone_path}")
        return self._clone_path

    def cleanup(self):
        """审查结束后删除临时 clone 目录。"""
        if self._clone_path and self._clone_path.exists():
            logger.debug(f"[Repo] 清理临时目录: {self._clone_path}")
            shutil.rmtree(self._clone_path, ignore_errors=True)
            self._clone_path = None
