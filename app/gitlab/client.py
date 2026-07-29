

import httpx
from app.config import get_settings

class GitLabClient:
    """GitLab REST API v4 封装。"""

    def __init__(self):
        settings = get_settings()
        self.base_url = f"{settings.gitlab_base_url}/api/v4"
        self.headers = {
            "PRIVATE-TOKEN": settings.gitlab_token,
            "Content-Type": "application/json",
        }

    async def create_mr_note(
        self, project_id: int, mr_iid: int, body: str
    ):
        """创建 MR 级别评论（摘要）。"""
        url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/notes"
        async with httpx.AsyncClient() as client:
            await client.post(url, headers=self.headers, json={"body": body})

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
        url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/discussions"
        payload = {
            "body": body,
            "position": {
                "base_sha": base_sha,
                "head_sha": head_sha,
                "start_sha": start_sha,
                "position_type": "text",
                "new_path": new_path,
                "new_line": new_line,
            },
        }
        async with httpx.AsyncClient() as client:
            await client.post(url, headers=self.headers, json=payload)

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
        async with httpx.AsyncClient() as client:
            await client.post(url, headers=self.headers, json=payload)

    async def get_mr_diff(self, project_id: int, mr_iid: int) -> list[dict]:
        """
        获取 MR 的变更文件列表。
        返回 [{old_path, new_path, diff, new_file, deleted_file, ...}]
        """
        url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/changes"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers)
            data = resp.json()
            return data.get("changes", [])

    async def get_mr_detail(self, project_id: int, mr_iid: int) -> dict:
        """获取 MR 详情（含 sha、source_branch 等）。"""
        url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers)
            return resp.json()
