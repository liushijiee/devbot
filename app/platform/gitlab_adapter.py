"""
GitLab 平台适配器（入站 + 出站）。

入站：X-Gitlab-Token 校验 + Merge Request Hook / action 过滤 + 提取 ReviewContext。
出站：复用 GitLabClient（httpx）发评论 / status / 取 diff。

所有 GitLab 专属细节（headers、/api/v4 路径、Discussions API、
failed vs failure、token 注入 repo_url）都关在这里，编排层看不到。
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Request

from app.config import get_settings
from app.gitlab.client import GitLabClient
from app.platform.base import PlatformAdapter, ReviewContext

logger = logging.getLogger(__name__)


class GitLabAdapter:
    """GitLab 实现 PlatformAdapter。"""

    platform = "gitlab"

    def __init__(self):
        self.settings = get_settings()
        # 启动 fail-fast：缺 GitLab 凭证直接启动失败（对齐 openreview env 校验）
        self.settings.assert_gitlab_ready()
        self._client = GitLabClient()

    # ── 入站 ──
    def verify(self, request: Request) -> bool:
        secret = self.settings.gitlab_webhook_secret
        # 密钥未配置时绝不「空串相等」放行，直接拒绝所有请求
        if not secret:
            logger.error("[Webhook] 未配置 GITLAB_WEBHOOK_SECRET，拒绝所有请求")
            return False
        token = request.headers.get("X-Gitlab-Token", "")
        # 常量时间比较，避免时序侧信道
        return hmac.compare_digest(token.encode(), secret.encode())

    async def parse(self, request: Request) -> ReviewContext | None:
        event = request.headers.get("X-Gitlab-Event", "")
        if event != "Merge Request Hook":
            logger.info(f"[GitLabAdapter] 忽略非 MR 事件: {event}")
            return None

        data = await request.json()
        action = data.get("object_attributes", {}).get("action")
        mr_iid = data.get("object_attributes", {}).get("iid", "?")
        project_name = data.get("project", {}).get("name", "?")
        logger.info(f"[GitLabAdapter] MR !{mr_iid} | 项目: {project_name} | action: {action}")

        if action not in ("open", "update"):
            logger.info(f"[GitLabAdapter] 忽略 action: {action}")
            return None

        mr_attrs = data["object_attributes"]
        project_id = data["project"]["id"]
        head_sha = mr_attrs.get("last_commit", {}).get("id", "")
        source_branch = mr_attrs.get("source_branch", "main")

        repo_url = data["project"].get("git_http_url", "")
        if self.settings.gitlab_token and repo_url.startswith("https://"):
            repo_url = repo_url.replace("https://", f"https://oauth2:{self.settings.gitlab_token}@")

        return ReviewContext(
            platform="gitlab",
            project_ref=project_id,
            mr_id=mr_iid,
            head_sha=head_sha,
            source_branch=source_branch,
            repo_url=repo_url,
            raw=data,
        )

    # ── 出站 ──
    async def get_diff(self, ctx: ReviewContext) -> list[dict]:
        return await self._client.get_mr_diff(ctx.project_ref, ctx.mr_id)

    async def get_shas(self, ctx: ReviewContext) -> tuple[str, str, str]:
        detail = await self._client.get_mr_detail(ctx.project_ref, ctx.mr_id)
        refs = detail.get("diff_refs", {})
        base = refs.get("base_sha", "")
        start = refs.get("start_sha", "")
        head = refs.get("head_sha", ctx.head_sha)
        return base, start, head

    async def set_status(self, ctx: ReviewContext, state: str, description: str) -> None:
        # GitLab 直接使用逻辑值（failed 即 GitLab 原生值）
        await self._client.set_commit_status(ctx.project_ref, ctx.head_sha, state, description)

    async def post_summary(self, ctx: ReviewContext, body: str) -> None:
        await self._client.create_mr_note(ctx.project_ref, ctx.mr_id, body)

    async def post_comment(
        self,
        ctx: ReviewContext,
        comment: dict,
        base_sha: str,
        start_sha: str,
        head_sha: str,
    ) -> None:
        line = comment.get("line")
        if line and isinstance(line, int) and line >= 1:
            await self._client.create_line_comment(
                project_id=ctx.project_ref,
                mr_iid=ctx.mr_id,
                body=comment["body"],
                new_path=comment["file"],
                new_line=line,
                base_sha=base_sha,
                head_sha=head_sha,
                start_sha=start_sha,
                old_line=comment.get("old_line"),
            )
        else:
            # 无法定位行号 → 降级为 MR 级评论（带 路径 前缀），保证信息不丢
            fallback_body = f"📍 `{comment['file']}`\n\n{comment['body']}"
            await self._client.create_mr_note(ctx.project_ref, ctx.mr_id, fallback_body)
