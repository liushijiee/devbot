

import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

class GitLabClient:
    """GitLab REST API v4 封装。"""

    def __init__(self):
        settings = get_settings()
        self.base_url = f"{settings.gitlab_base_url}/api/v4"
        self.headers = {
            "PRIVATE-TOKEN": settings.gitlab_token,
            "Content-Type": "application/json",
        }
        logger.debug(f"[GitLab] 初始化客户端 → {self.base_url}")

    async def create_mr_note(
        self, project_id: int, mr_iid: int, body: str
    ):
        """创建 MR 级别评论（摘要）。"""
        url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/notes"
        logger.debug(f"[GitLab] POST 摘要评论 → MR !{mr_iid} ({len(body)} 字符)")
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self.headers, json={"body": body})
            logger.debug(f"[GitLab] 摘要评论响应: {resp.status_code}")

    async def create_line_comment(
        self,
        project_id: int,
        mr_iid: int,
        body: str,
        new_path: str,
        new_line: int,
        base_sha: str,
        head_sha: str,
        start_sha: str,
    ):
        """
        创建行级评论（通过 Discussion API）。
        GitLab 行级评论需要 position 对象，比 GitHub 复杂。
        """
        if not new_line or new_line < 1:
            logger.warning(f"[GitLab] 行号无效({new_line})，跳过行级评论: {new_path}")
            return

        url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/discussions"
        payload = {
            "body": body,
            "position": {
                "base_sha": base_sha,
                "head_sha": head_sha,
                "start_sha": start_sha,
                "position_type": "text",
                "old_path": new_path,
                "new_path": new_path,
                "new_line": new_line,
            },
        }
        logger.debug(f"[GitLab] POST 行级评论 → {new_path}:{new_line}")
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self.headers, json=payload)
            if resp.status_code >= 400:
                logger.warning(f"[GitLab] 行级评论失败: {resp.status_code} {resp.text[:200]}")
            else:
                logger.debug(f"[GitLab] 行级评论成功: {resp.status_code}")

    async def set_commit_status(
        self,
        project_id: int,
        sha: str,
        state: str,
        description: str,
    ):
        """
        设置 Commit Status。
        state: "success" | "failed" | "pending" | "running"
        注意：GitLab 用 "failed"，GitHub 用 "failure"。
        """
        url = f"{self.base_url}/projects/{project_id}/statuses/{sha}"
        payload = {
            "state": state,
            "description": description,
            "name": "devbot/review",
        }
        logger.debug(f"[GitLab] POST Commit Status → {state}: {description}")
        async with httpx.AsyncClient() as client:
            await client.post(url, headers=self.headers, json=payload)

    async def get_mr_diff(self, project_id: int, mr_iid: int) -> list[dict]:
        """
        获取 MR 的变更文件列表。
        返回 [{old_path, new_path, diff, new_file, deleted_file, ...}]
        """
        url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/changes"
        logger.debug(f"[GitLab] GET MR diff → project={project_id} mr=!{mr_iid}")
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers)
            data = resp.json()
            changes = data.get("changes", [])
            logger.debug(f"[GitLab] MR diff 响应: {resp.status_code}, {len(changes)} 个文件")
            return changes

    async def get_mr_detail(self, project_id: int, mr_iid: int) -> dict:
        """获取 MR 详情（含 sha、source_branch 等）。"""
        url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}"
        logger.debug(f"[GitLab] GET MR 详情 → !{mr_iid}")
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers)
            return resp.json()
