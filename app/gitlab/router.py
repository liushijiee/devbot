"""
GitLab Webhook 路由（瘦）。

职责收紧为一行流水线：校验 → 解析 → 异步触发编排。
所有数据加工已迁入 GitLabAdapter；编排逻辑迁入 review.pipeline。
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request, HTTPException

from app.platform.gitlab_adapter import GitLabAdapter
from app.platform.session import ReviewSession
from app.review.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()

_adapter = GitLabAdapter()


@router.post("/gitlab")
async def gitlab_webhook(request: Request):
    if not _adapter.verify(request):
        logger.warning("[Webhook] Token 验证失败")
        raise HTTPException(status_code=403, detail="Invalid token")

    ctx = await _adapter.parse(request)
    if ctx is None:
        return {"msg": "ignored event"}

    session = ReviewSession.from_context(ctx, _adapter)
    logger.info(f"[Webhook] 启动异步审查任务 mr=!{session.mr_id} session={session.session_id}")
    asyncio.create_task(run_pipeline(session))
    return {"msg": "review started", "mr": session.mr_id}
