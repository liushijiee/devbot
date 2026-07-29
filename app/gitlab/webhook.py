
import asyncio
import logging

from fastapi import APIRouter, Request, HTTPException

from app.config import get_settings
from app.gitlab.client import GitLabClient
from app.graph.builder import run_review

logger = logging.getLogger(__name__)
router = APIRouter()

def verify_token(request_token: str, secret: str) -> bool:
    return request_token == secret

@router.post("/gitlab")
async def gitlab_webhook(request: Request):
    settings = get_settings()

    token = request.headers.get("X-Gitlab-Token", "")
    if not verify_token(token, settings.gitlab_webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid token")

    event = request.headers.get("X-Gitlab-Event", "")
    if event != "Merge Request Hook":
        return {"msg": f"ignored event: {event}"}

    data = await request.json()
    action = data.get("object_attributes", {}).get("action")

    if action not in ("open", "update"):
        return {"msg": f"ignored action: {action}"}

    asyncio.create_task(_run_review(data))

    mr_iid = data["object_attributes"]["iid"]
    return {"msg": "review started", "mr": mr_iid}

async def _run_review(webhook_data: dict):
    """
    评审主流程：Webhook → LangGraph → GitLab 评论。
    异步执行，不阻塞 Webhook 的 200 响应。
    """
    settings = get_settings()
    gitlab = GitLabClient()

    mr_attrs = webhook_data["object_attributes"]
    project_id = webhook_data["project"]["id"]
    mr_iid = mr_attrs["iid"]
    head_sha = mr_attrs.get("last_commit", {}).get("id", "")
    source_branch = mr_attrs.get("source_branch", "main")

    repo_url = webhook_data["project"].get("git_http_url", "")
    if settings.gitlab_token and repo_url.startswith("https://"):

        repo_url = repo_url.replace("https://", f"https://oauth2:{settings.gitlab_token}@")

    logger.info(f"[DevBot] 开始审查 Project #{project_id} MR !{mr_iid}")

    try:

        if head_sha:
            await gitlab.set_commit_status(
                project_id, head_sha, "running", "DevBot 正在审查..."
            )

        changes = await gitlab.get_mr_diff(project_id, mr_iid)
        if not changes:
            logger.warning(f"MR !{mr_iid} 无变更文件，跳过审查")
            if head_sha:
                await gitlab.set_commit_status(
                    project_id, head_sha, "success", "无变更文件"
                )
            return

        result = await run_review(
            changes=changes,
            repo_url=repo_url,
            branch=source_branch,
            mr_iid=mr_iid,
            project_id=project_id,
        )

        summary = result.get("summary", "")
        comments = result.get("comments", [])
        risk_score = result.get("risk_score", 0)

        if summary:
            await gitlab.create_mr_note(project_id, mr_iid, summary)

        mr_detail = await gitlab.get_mr_detail(project_id, mr_iid)
        base_sha = mr_detail.get("diff_refs", {}).get("base_sha", "")
        start_sha = mr_detail.get("diff_refs", {}).get("start_sha", "")
        head_sha_detail = mr_detail.get("diff_refs", {}).get("head_sha", head_sha)

        for comment in comments:
            try:
                await gitlab.create_line_comment(
                    project_id=project_id,
                    mr_iid=mr_iid,
                    body=comment["body"],
                    new_path=comment["file"],
                    new_line=comment["line"],
                    base_sha=base_sha,
                    head_sha=head_sha_detail,
                    start_sha=start_sha,
                )
            except Exception as e:

                logger.warning(f"行级评论失败 ({comment['file']}:{comment['line']}): {e}")

        if head_sha:
            if risk_score >= settings.risk_block_threshold:
                await gitlab.set_commit_status(
                    project_id, head_sha, "failed",
                    f"风险分 {risk_score}/100，建议阻断合并"
                )
            else:
                await gitlab.set_commit_status(
                    project_id, head_sha, "success",
                    f"审查通过，风险分 {risk_score}/100"
                )

        logger.info(
            f"[DevBot] MR !{mr_iid} 审查完成: "
            f"risk={risk_score}, comments={len(comments)}"
        )

    except Exception as e:
        logger.error(f"[DevBot] MR !{mr_iid} 审查失败: {e}", exc_info=True)

        if head_sha:
            try:
                await gitlab.set_commit_status(
                    project_id, head_sha, "failed", f"审查异常: {str(e)[:100]}"
                )
            except Exception:
                pass
