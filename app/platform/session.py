"""
ReviewSession：把「平台无关快照 ReviewContext」+「平台适配器」+ 稳定标识打包成
一个可寻址的审查单元。

对标 openreview 的 Thread，但刻意去掉聊天 / 会话 / 状态包袱：
- ctx:       由 adapter.parse() 产出的平台无关快照（纯数据）
- adapter:   内联的平台适配器（能力），编排层从此不再单独传 adapter
- session_id: 稳定标识，用于并发去重 / 跨事件关联（按需使用，不属于“状态”）
- 出站 I/O 直接以方法形式暴露，内部委托给 adapter，调用方只认 session

设计边界（Phase 1）：
- 不含 state（跨事件持久态）—— 本次未引入
- 不含消息历史 / reaction —— 审查 bot 无会话
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.platform.base import PlatformAdapter, ReviewContext


@dataclass
class ReviewSession:
    """一次 MR 审查的可寻址单元：数据(ctx) + 能力(adapter) + 稳定标识(session_id)。"""

    ctx: ReviewContext
    adapter: PlatformAdapter
    session_id: str = field(default_factory=lambda: uuid4().hex)

    # ── 便捷只读访问：编排层像用 Thread 一样用 session.<field> ──
    @property
    def platform(self) -> str:
        return self.ctx.platform

    @property
    def project_ref(self) -> str | int:
        return self.ctx.project_ref

    @property
    def mr_id(self) -> int:
        return self.ctx.mr_id

    @property
    def head_sha(self) -> str:
        return self.ctx.head_sha

    @property
    def source_branch(self) -> str:
        return self.ctx.source_branch

    @property
    def repo_url(self) -> str:
        return self.ctx.repo_url

    @property
    def raw(self) -> dict:
        return self.ctx.raw

    # ── 构造工厂：从 adapter.parse() 产出的 ReviewContext 升级而来 ──
    @classmethod
    def from_context(cls, ctx: ReviewContext, adapter: PlatformAdapter) -> "ReviewSession":
        return cls(ctx=ctx, adapter=adapter)

    # ── 出站 I/O（委托给 adapter，调用方只认 session） ──
    async def get_diff(self) -> list[dict]:
        return await self.adapter.get_diff(self.ctx)

    async def get_shas(self) -> tuple[str, str, str]:
        return await self.adapter.get_shas(self.ctx)

    async def set_status(self, state: str, description: str) -> None:
        await self.adapter.set_status(self.ctx, state, description)

    async def post_summary(self, body: str) -> None:
        await self.adapter.post_summary(self.ctx, body)

    async def post_comment(
        self,
        comment: dict,
        base_sha: str,
        start_sha: str,
        head_sha: str,
    ) -> None:
        await self.adapter.post_comment(self.ctx, comment, base_sha, start_sha, head_sha)
