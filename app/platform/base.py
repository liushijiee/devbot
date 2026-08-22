"""
平台无关抽象层（借鉴 openreview / chat SDK 的 adapter 思想）。

定义两样东西，让审查编排（run_pipeline）彻底脱离具体代码平台：

1. ReviewContext：一次审查请求的“平台无关快照”。
   GitLab 的 project_id 与 GitHub 的 "owner/repo" 都收敛成同一个结构。
2. PlatformAdapter（Protocol）：编排层只依赖这组接口，
   具体验签 / 解析 / 发评论 / 发 status 由 GitLab / GitHub adapter 各自实现。

设计约束（Phase 1 锁定）：
- run_review() 与 eval 链路不动，因此 adapter.get_diff() 返回的是
  run_review 能直接吃的 “GitLab 形状 changes”（GitHub adapter 后续负责转换）。
- 不引入对话线程模型（Thread / Message），审查 bot 无会话，不需要。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import Request


@dataclass
class ReviewContext:
    """一次 MR / PR 审查请求的平台无关快照。"""

    platform: str                      # "gitlab" / "github"
    project_ref: str | int            # gitlab: project_id；github: "owner/repo"
    mr_id: int                        # gitlab: iid；github: PR number
    head_sha: str
    source_branch: str
    repo_url: str                     # 已注入访问凭证
    base_sha: str = ""
    start_sha: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class PlatformAdapter(Protocol):
    """编排层（run_pipeline）依赖的唯一接口。"""

    platform: str

    def verify(self, request: Request) -> bool:
        """校验 webhook 来源（GitLab: X-Gitlab-Token；GitHub: HMAC）。"""
        ...

    async def parse(self, request: Request) -> ReviewContext | None:
        """
        解析 webhook 为 ReviewContext。
        返回 None 表示事件被忽略（非目标事件 / 非目标 action），router 直接 200。
        """
        ...

    async def get_diff(self, ctx: ReviewContext) -> list[dict]:
        """返回 run_review 能直接消费的 changes（GitLab 形状）。"""
        ...

    async def get_shas(self, ctx: ReviewContext) -> tuple[str, str, str]:
        """返回 (base_sha, start_sha, head_sha)，用于行级评论定位。"""
        ...

    async def set_status(self, ctx: ReviewContext, state: str, description: str) -> None:
        """
        设置 commit / check status。
        state 为逻辑值："running" | "success" | "failed"，
        具体映射（GitLab failed vs GitHub failure）由 adapter 负责。
        """
        ...

    async def post_summary(self, ctx: ReviewContext, body: str) -> None:
        """发布 MR / PR 级摘要评论。"""
        ...

    async def post_comment(
        self,
        ctx: ReviewContext,
        comment: dict,
        base_sha: str,
        start_sha: str,
        head_sha: str,
    ) -> None:
        """
        发布单条审查评论。
        comment 含 file / line / old_line / body；行号无效时由 adapter 降级为文件级评论。
        """
        ...
