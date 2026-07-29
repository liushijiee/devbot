"""
DevBot — FastAPI 入口
接收 GitLab Webhook，异步触发 MR 评审流程。
"""

import logging
import sys

from fastapi import FastAPI
from app.gitlab.webhook import router as webhook_router

# ── 全局日志配置 ──
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s │ %(levelname)-7s │ %(name)-28s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# 降低第三方库噪音
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

app = FastAPI(title="DevBot", description="智能 PR 评审 Agent")

app.include_router(webhook_router, prefix="/webhook")

@app.on_event("startup")
async def startup():
    logger.info("="*60)
    logger.info("DevBot 启动完成")
    logger.info("="*60)

@app.get("/health")
async def health():
    return {"status": "ok"}
