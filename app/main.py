
from fastapi import FastAPI
from app.gitlab.webhook import router as webhook_router

app = FastAPI(title="DevBot", description="智能 PR 评审 Agent")

app.include_router(webhook_router, prefix="/webhook")

@app.get("/health")
async def health():
    return {"status": "ok"}
