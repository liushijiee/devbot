"""
LangGraph 图构建器
将所有节点组装为完整的审查流水线。

图结构（单 bundle 处理器）：
  prepare ──→ Send × 4 Critics（并行）──→ aggregate

多 bundle 编排由 run_review 负责（Harness 层）：
  parse → filter → group → [循环每个 bundle 调用图] → 合并 → reflect → report

关键机制：
- Send API: 确定性扇出到 4 个 Critic
- operator.add reducer: 并行 Critic 的结果自动合并
- run_review 循环所有 bundle，确保大 MR 不遗漏
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from app.config import get_settings
from app.graph.state import ReviewState, CriticResult, Finding, TokenUsage
from app.graph.nodes import (
    prepare,
    aggregate,
    reflect,
    report,
    _get_llm,
    _parse_findings,
    _deduplicate,
    _extract_token_usage,
)
from app.harness.diff_parser import parse_gitlab_changes, FileChange
from app.harness.file_filter import filter_files
from app.harness.file_grouper import group_files, Bundle
from app.harness.rule_matcher import match_rules
from app.harness.repo_manager import RepoManager
from app.harness.position_fixer import fix_positions
from app.prompts.registry import CRITIC_NAMES
from app.tools.code_tools import create_tools
from app.graph.tracer import trace_node

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger(__name__)

# ── Checkpoint 持久化 ──
CHECKPOINT_DIR = Path(__file__).resolve().parent.parent.parent / "checkpoints"

def _checkpoint_path(key: str) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"{key}.json"

def _load_checkpoint(key: str) -> dict | None:
    """加载 Checkpoint，不存在或损坏返回 None。"""
    if not key:
        return None
    path = _checkpoint_path(key)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

def _save_checkpoint(key: str, data: dict):
    """保存 Checkpoint（每完成一个 bundle 调用一次）。"""
    if not key:
        return
    path = _checkpoint_path(key)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _cleanup_checkpoint(key: str):
    """审查成功后清理 Checkpoint。"""
    if not key:
        return
    path = _checkpoint_path(key)
    if path.exists():
        path.unlink()

def _bundle_hash(diff_text: str) -> str:
    """对 bundle 的 diff 内容计算指纹（MD5 前 16 位）。"""
    return hashlib.md5(diff_text.encode()).hexdigest()[:16]


@trace_node("3. build_review_graph")
def build_review_graph(repo_manager: RepoManager, file_changes: list[FileChange]):
    """
    构建单 bundle 审查图。

    图结构: prepare → critics(×4) → aggregate
    reflect 和 report 由 run_review 在图外调用（因为需要跨 bundle 合并后再验证）。
    """
    settings = get_settings()

    def prepare_node(state: ReviewState) -> dict:
        """Harness 层处理。"""
        return prepare(state)

    @trace_node("node2. route_to_critics")
    def route_to_critics(state: ReviewState) -> list[Send]:
        """
        确定性扇出：为每个 Critic 创建一个 Send。
        这是 Harness 层的“确定性启动”——不是 LLM 决定启动几个 Critic。
        """
    
        if not state.get("diff_text"):
            logger.info("[Route] 无 diff，跳过 Critic 直接聚合")
            return [Send("aggregate", state)]
    
        logger.info(f"[Route] 扇出 {len(CRITIC_NAMES)} 个 Critic: {CRITIC_NAMES}")
        return [
            Send("critic_node", {"critic_name": name, **state})
            for name in CRITIC_NAMES
        ]

    @trace_node("node3. critic_node")
    async def critic_node(state: dict) -> dict:
        """
        单个 Critic 节点（带指数退避重试）。
        接收 Send 传入的 state（含 critic_name），运行 ReAct Agent。
        失败时最多重试 2 次（延迟 1s, 2s），避免 LLM API 瞬时故障导致审查中断。
        """
        critic_name = state["critic_name"]
        logger.info(f"[CriticNode] ══ 启动: {critic_name} ══")

        max_retries = 2
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                from app.prompts.registry import load_prompt
                template = load_prompt(critic_name)
                system_prompt = template.system
                user_prompt = template.format_user(
                    changed_files=state.get("changed_files", ""),
                    diff_text=state.get("diff_text", ""),
                    rules=state.get("rules", ""),
                )

                tools = create_tools(repo_manager, file_changes)
                llm = _get_llm()
                agent = create_react_agent(
                    model=llm,
                    tools=tools,
                    prompt=SystemMessage(content=system_prompt),
                )
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=user_prompt)]},
                    config={"recursion_limit": settings.max_tool_rounds * 2 + 5},
                )

                last_message = result["messages"][-1].content
                findings = _parse_findings(last_message, critic_name)
                findings = fix_positions(findings, state.get("diff_text", ""))

                token_usage = _extract_token_usage(result["messages"])

                critic_result: CriticResult = {
                    "critic_name": critic_name,
                    "findings": findings,
                    "error": None,
                }
                logger.info(
                    f"[CriticNode] {critic_name} 完成 → {len(findings)} findings"
                    f" | token: in={token_usage['input_tokens']}, out={token_usage['output_tokens']}, calls={token_usage['llm_calls']}"
                )
                return {"critic_results": [critic_result], "token_usage": token_usage}

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = 1.0 * (2 ** attempt)  # 1s, 2s
                    logger.warning(
                        f"[CriticNode] {critic_name} 第{attempt+1}次失败, {delay:.1f}s后重试: {e}"
                    )
                    await asyncio.sleep(delay)

        # 所有重试都失败
        logger.error(f"[CriticNode] {critic_name} 重试{max_retries}次后仍失败: {last_error}", exc_info=True)
        critic_result: CriticResult = {
            "critic_name": critic_name,
            "findings": [],
            "error": str(last_error),
        }
        token_usage: TokenUsage = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}
        return {"critic_results": [critic_result], "token_usage": token_usage}

    graph = StateGraph(ReviewState)

    graph.add_node("prepare", prepare_node)
    graph.add_node("critic_node", critic_node)
    graph.add_node("aggregate", aggregate)

    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", route_to_critics, ["critic_node", "aggregate"])
    graph.add_edge("critic_node", "aggregate")
    graph.add_edge("aggregate", END)

    logger.debug("[Builder] 图构建完成: prepare → critics(×4) → aggregate")
    return graph.compile()

@trace_node("0. run_review")
async def run_review(
    changes: list[dict],
    repo_url: str,
    branch: str,
    mr_iid: int = 0,
    project_id: int = 0,
    head_sha: str = "",
) -> dict:
    """
    执行完整审查流程（多 bundle 支持 + Checkpoint 断点续跑）。

    流程：
    1. clone 仓库
    2. parse → filter → group → 得到所有 bundles
    3. 对每个 bundle 调用图（prepare → critics → aggregate）
       - 每完成一个 bundle 持久化 Checkpoint
       - 进程崩溃后重新触发时从 Checkpoint 续跑
    4. 合并所有 bundle 的 findings + 去重
    5. reflect（带工具验证）
    6. report（风险分 + 评论）
    """
    settings = get_settings()
    repo_manager = RepoManager()
    ckpt_key = f"{project_id}_{mr_iid}" if project_id and mr_iid else ""

    try:
        safe_url = repo_url.split('@')[-1] if '@' in repo_url else repo_url[:60]
        logger.info(f"[RunReview] 开始 clone 仓库: {safe_url} | branch={branch}")
        await repo_manager.clone(repo_url, branch)
        logger.info(f"[RunReview] 仓库已 clone 到: {repo_manager.clone_path}")

        # ── Harness 层：解析 → 过滤 → 分组 ──
        file_changes = parse_gitlab_changes(changes)
        filtered = filter_files(file_changes)

        if not filtered:
            logger.info("[RunReview] 过滤后无文件，跳过审查")
            return {"risk_score": 0, "summary": "✅ 无需审查的文件。", "comments": []}

        bundles = group_files(filtered)
        all_file_paths = [f.path for f in filtered]
        logger.info(f"[RunReview] {len(filtered)} 个文件，分为 {len(bundles)} 个 bundle")

        # ── 加载 Checkpoint（基于 bundle diff 内容 hash 判断是否已完成）──
        ckpt = _load_checkpoint(ckpt_key)
        completed_cache: dict[str, dict] = {}  # {bundle_hash: {findings, file_paths}}
        all_aggregated_findings: list[Finding] = []
        total_token_usage: TokenUsage = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}
        if ckpt:
            completed_cache = ckpt.get("completed", {})
            total_token_usage = ckpt.get("token_usage", {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0})
            logger.info(f"[RunReview] 加载 Checkpoint: 已有 {len(completed_cache)} 个已完成 bundle 缓存")

        # ── 构建图（单 bundle 处理器）──
        graph = build_review_graph(repo_manager, file_changes)

        # ── 循环所有 bundle ──
        for idx, bundle in enumerate(bundles, 1):
            b_hash = _bundle_hash(bundle.diff_text)

            # 基于 diff 内容 hash 判断是否已完成
            if b_hash in completed_cache:
                cached = completed_cache[b_hash]
                all_aggregated_findings.extend(cached.get("findings", []))
                logger.info(f"[RunReview] Bundle {idx} diff 未变 (hash={b_hash[:8]})，复用缓存 {len(cached.get('findings', []))} 个 findings")
                continue
            logger.info(f"[RunReview] ══ Bundle {idx}/{len(bundles)} ══ ({bundle.total_lines} 行, {len(bundle.files)} 文件)")

            rules_text = match_rules(bundle.files)
            bundle_paths = [f.path for f in bundle.files]
            changed_files_text = "\n".join(f"- {p}" for p in bundle_paths)

            initial_state: ReviewState = {
                "changes": changes,
                "repo_url": repo_url,
                "branch": branch,
                "mr_iid": mr_iid,
                "project_id": project_id,
                "diff_text": bundle.diff_text,
                "changed_files": changed_files_text,
                "rules": rules_text,
                "all_file_paths": all_file_paths,
            }

            result = await graph.ainvoke(initial_state)
            bundle_findings = result.get("aggregated_findings", [])
            logger.info(f"[RunReview] Bundle {idx} 完成 → {len(bundle_findings)} 个 findings")
            all_aggregated_findings.extend(bundle_findings)

            # 聚合本 bundle 的 Critic token 消耗
            bundle_usage = result.get("token_usage", {})
            total_token_usage["input_tokens"] += bundle_usage.get("input_tokens", 0)
            total_token_usage["output_tokens"] += bundle_usage.get("output_tokens", 0)
            total_token_usage["llm_calls"] += bundle_usage.get("llm_calls", 0)

            # ── 保存 Checkpoint（基于 bundle diff hash）──
            if ckpt_key:
                completed_cache[b_hash] = {
                    "file_paths": bundle.file_paths,
                    "findings": bundle_findings,
                }
                _save_checkpoint(ckpt_key, {
                    "completed": completed_cache,
                    "token_usage": total_token_usage,
                })

        # ── 跨 bundle 去重 ──
        all_aggregated_findings = _deduplicate(all_aggregated_findings)
        logger.info(f"[RunReview] 全部 bundle 合并去重后: {len(all_aggregated_findings)} 个 findings")

        # ── Reflect（带工具验证）──
        reflect_state: ReviewState = {
            "aggregated_findings": all_aggregated_findings,
            "diff_text": "\n".join(b.diff_text for b in bundles),
            "all_file_paths": all_file_paths,
        }
        reflect_result = await reflect(reflect_state, repo_manager, file_changes)
        verified_findings = reflect_result.get("verified_findings", [])

        # 聚合 Reflector 的 token 消耗
        reflect_usage = reflect_result.get("reflect_token_usage", {})
        total_token_usage["input_tokens"] += reflect_usage.get("input_tokens", 0)
        total_token_usage["output_tokens"] += reflect_usage.get("output_tokens", 0)
        total_token_usage["llm_calls"] += reflect_usage.get("llm_calls", 0)

        # ── 对 Reflector 修改过的 findings 重新定位行号 ──
        # Reflector 可能修改了 existing_code，需要重新计算 line
        diff_text_combined = "\n".join(b.diff_text for b in bundles)
        verified_findings = fix_positions(verified_findings, diff_text_combined)

        # ── Report ──
        report_state: ReviewState = {"verified_findings": verified_findings}
        final = report(report_state)

        logger.info(
            f"[RunReview] ══ 审查完成 ══ risk={final['risk_score']}/100, comments={len(final['comments'])}"
            f" | token 总计: in={total_token_usage['input_tokens']}, out={total_token_usage['output_tokens']}, calls={total_token_usage['llm_calls']}"
        )

        return final

    finally:
        repo_manager.cleanup()
        logger.info("[RunReview] 临时仓库已清理")
