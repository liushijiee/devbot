"""
平台无关审查编排（= openreview 的 handleMention / botWorkflow）。

只认 ReviewSession（= ReviewContext 数据 + 内联 PlatformAdapter 能力），
不 import 任何 GitLab / GitHub 专属代码。所有平台 I/O 都通过 session 的方法完成。

run_review()（LangGraph 核心）签名保持不变，eval 链路零改动。
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.graph.builder import run_review
from app.platform.session import ReviewSession

logger = logging.getLogger(__name__)


async def run_pipeline(session: ReviewSession) -> None:
    """
    审查主流程：不阻塞 webhook 200 的那段异步逻辑。
    异常统一在末尾把 status 标 failed。
    """
    settings = get_settings()
    logger.info(
        f"[Pipeline] ══ 开始 ══ {session.platform} project={session.project_ref} "
        f"mr=!{session.mr_id} session={session.session_id}"
    )

    try:
        if session.head_sha:
            await session.set_status("running", "DevBot 正在审查...")

        changes = await session.get_diff()
        logger.info(f"[Pipeline] 获取到 {len(changes)} 个变更文件")
        if not changes:
            logger.warning(f"MR !{session.mr_id} 无变更文件，跳过审查")
            if session.head_sha:
                await session.set_status("success", "无变更文件")
            return

        result = await run_review(
            changes=changes,
            repo_url=session.repo_url,
            branch=session.source_branch,
            mr_iid=session.mr_id,
            project_id=session.project_ref,
        )

        summary = result.get("summary", "")
        comments = result.get("comments", [])
        risk_score = result.get("risk_score", 0)
        logger.info(f"[Pipeline] 审查完成 → risk={risk_score}, comments={len(comments)}")

        if summary:
            await session.post_summary(summary)

        base_sha, start_sha, head_sha = await session.get_shas()
        for comment in comments:
            try:
                await session.post_comment(comment, base_sha, start_sha, head_sha)
            except Exception as e:
                logger.warning(f"[Pipeline] 评论发布失败 {comment.get('file', '?')} → {e}")

        if session.head_sha:
            if risk_score >= settings.risk_block_threshold:
                await session.set_status("failed", f"风险分 {risk_score}/100，建议阻断合并")
            else:
                await session.set_status("success", f"审查通过，风险分 {risk_score}/100")

        logger.info(
            f"[Pipeline] ══ 完成 ══ mr=!{session.mr_id} | risk={risk_score}/100 | comments={len(comments)}"
        )

    except Exception as e:
        logger.error(f"[Pipeline] MR !{session.mr_id} 审查失败: {e}", exc_info=True)
        if session.head_sha:
            try:
                await session.set_status("failed", f"审查异常: {str(e)[:100]}")
            except Exception:
                pass
