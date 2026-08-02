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

import logging
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from app.config import get_settings
from app.graph.state import ReviewState, CriticResult, Finding
from app.graph.nodes import (
    prepare,
    aggregate,
    reflect,
    report,
    _get_llm,
    _parse_findings,
    _deduplicate,
)
from app.harness.diff_parser import parse_gitlab_changes, FileChange
from app.harness.file_filter import filter_files
from app.harness.file_grouper import group_files, Bundle
from app.harness.rule_matcher import match_rules
from app.harness.repo_manager import RepoManager
from app.prompts.registry import CRITIC_NAMES
from app.tools.code_tools import create_tools
from app.graph.tracer import trace_node

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger(__name__)

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
        单个 Critic 节点。
        接收 Send 传入的 state（含 critic_name），运行 ReAct Agent。
        """
        critic_name = state["critic_name"]
        logger.info(f"[CriticNode] ══ 启动: {critic_name} ══")

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

            logger.info(f"[tool] {', '.join(str(tool) for tool in tools)}")

            llm = _get_llm()
            agent = create_react_agent(
                model=llm,
                tools=tools,
                prompt=SystemMessage(content=system_prompt),
            )
            # logger.info(f"user_prompt: {user_prompt}")
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=user_prompt)]},
                config={"recursion_limit": settings.max_tool_rounds * 2 + 5},
            )

            last_message = result["messages"][-1].content
            findings = _parse_findings(last_message, critic_name)

            critic_result: CriticResult = {
                "critic_name": critic_name,
                "findings": findings,
                "error": None,
            }
            logger.info(f"[CriticNode] {critic_name} 完成 → {len(findings)} findings")

        except Exception as e:
            logger.error(f"[CriticNode] {critic_name} 失败: {e}", exc_info=True)
            critic_result: CriticResult = {
                "critic_name": critic_name,
                "findings": [],
                "error": str(e),
            }

        return {"critic_results": [critic_result]}

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
) -> dict:
    """
    执行完整审查流程（多 bundle 支持）。

    流程：
    1. clone 仓库
    2. parse → filter → group → 得到所有 bundles
    3. 对每个 bundle 调用图（prepare → critics → aggregate）
    4. 合并所有 bundle 的 findings + 去重
    5. reflect（带工具验证）
    6. report（风险分 + 评论）
    """
    settings = get_settings()
    repo_manager = RepoManager()

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

        # ── 构建图（单 bundle 处理器）──
        graph = build_review_graph(repo_manager, file_changes)

        # ── 循环所有 bundle ──
        all_aggregated_findings: list[Finding] = []

        for idx, bundle in enumerate(bundles, 1):
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

        # ── Report ──
        report_state: ReviewState = {"verified_findings": verified_findings}
        final = report(report_state)

        logger.info(f"[RunReview] ══ 审查完成 ══ risk={final['risk_score']}/100, comments={len(final['comments'])}")
        return final

    finally:
        repo_manager.cleanup()
        logger.info("[RunReview] 临时仓库已清理")
