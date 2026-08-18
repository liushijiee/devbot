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
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

# 40 位十六进制 = 完整 commit sha（评测场景按 PR 被审查时的 commit 拉代码）
_FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


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
        branch 为分支名/tag 时：git clone --depth=1 --single-branch
        branch 为完整 commit sha 时：init + fetch <sha>（git clone --branch 不支持 sha）
        """
        settings = get_settings()
        base_dir = Path(settings.repo_clone_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        self._clone_path = Path(tempfile.mkdtemp(dir=base_dir))
        # mkdtemp 会创建目录，先删掉交给 git 自己创建
        shutil.rmtree(self._clone_path)
        logger.info(f"[Repo] 开始 clone → {self._clone_path}")

        if _FULL_SHA_PATTERN.match(branch or ""):
            cmd = self._sha_checkout_commands(repo_url, branch)
        else:
            cmd = [
                "git", "clone",
                "--depth=1",
                "--single-branch",
                "--branch", branch,
                repo_url,
                str(self._clone_path),
            ]

        logger.debug(f"[Repo] 命令: {' '.join(cmd[:6])}...")
        try:
            await self._run_git(cmd)
        except RuntimeError:
            if _FULL_SHA_PATTERN.match(branch or ""):
                # sha 方式失败（远端不支持或网络问题）时降级为普通分支克隆
                logger.warning(f"[Repo] 按 sha 检出失败，降级为 --branch {branch} 重试")
                self._clone_path = Path(tempfile.mkdtemp(dir=base_dir))
                shutil.rmtree(self._clone_path)
                await self._run_git([
                    "git", "clone", "--depth=1", "--single-branch",
                    "--branch", branch, repo_url, str(self._clone_path),
                ])
            else:
                raise

        logger.info(f"[Repo] clone 完成: {self._clone_path}")
        return self._clone_path

    def _sha_checkout_commands(self, repo_url: str, sha: str) -> list[str]:
        """构造按 commit sha 检出的一条 git -C 链式命令（init → remote add → fetch → checkout）。"""
        p = str(self._clone_path)
        return [
            "git", "init", p, "&&",
            "git", "-C", p, "remote", "add", "origin", repo_url, "&&",
            "git", "-C", p, "fetch", "--depth=1", "origin", sha, "&&",
            "git", "-C", p, "checkout", "FETCH_HEAD",
        ]

    async def _run_git(self, cmd: list[str]):
        """执行 git 命令（跨平台：Windows 下用 shell 串联多条子命令）。"""
        loop = asyncio.get_event_loop()
        need_shell = "&&" in cmd
        if need_shell:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(" ".join(cmd), shell=True, capture_output=True, timeout=120),
            )
        else:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, timeout=120),
            )

        if result.returncode != 0:
            err_msg = result.stderr.decode(errors="replace")[:200]
            logger.error(f"[Repo] clone 失败: {err_msg}")
            raise RuntimeError(f"git clone failed: {err_msg}")

    def cleanup(self):
        """审查结束后删除临时 clone 目录。"""
        if self._clone_path and self._clone_path.exists():
            logger.debug(f"[Repo] 清理临时目录: {self._clone_path}")
            shutil.rmtree(self._clone_path, ignore_errors=True)
            self._clone_path = None
