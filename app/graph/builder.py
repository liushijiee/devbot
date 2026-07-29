

import logging
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from app.config import get_settings
from app.graph.state import ReviewState, CriticResult
from app.graph.nodes import (
    prepare,
    run_critic,
    aggregate,
    reflect,
    report,
    _get_llm,
    _parse_findings,
)
from app.harness.diff_parser import parse_gitlab_changes, FileChange
from app.harness.file_filter import filter_files
from app.harness.repo_manager import RepoManager
from app.prompts.registry import CRITIC_NAMES
from app.tools.code_tools import create_tools

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger(__name__)

def build_review_graph(repo_manager: RepoManager, file_changes: list[FileChange]):
    """
    构建审查图。

    参数:
        repo_manager: 已 clone 的仓库管理器
        file_changes: 本次 MR 的变更文件列表

    返回:
        编译后的 LangGraph 图，可直接 .ainvoke(state) 执行
    """
    settings = get_settings()

    def prepare_node(state: ReviewState) -> dict:
        """Harness 层处理。"""
        return prepare(state)

    def route_to_critics(state: ReviewState) -> list[Send]:
        """
        确定性扇出：为每个 Critic 创建一个 Send。
        这是 Harness 层的"确定性启动"——不是 LLM 决定启动几个 Critic。
        """

        if not state.get("diff_text"):
            return [Send("aggregate", state)]

        return [
            Send("critic_node", {"critic_name": name, **state})
            for name in CRITIC_NAMES
        ]

    async def critic_node(state: dict) -> dict:
        """
        单个 Critic 节点。
        接收 Send 传入的 state（含 critic_name），运行 ReAct Agent。
        """
        critic_name = state["critic_name"]

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

            critic_result: CriticResult = {
                "critic_name": critic_name,
                "findings": findings,
                "error": None,
            }

        except Exception as e:
            logger.error(f"Critic [{critic_name}] 失败: {e}")
            critic_result: CriticResult = {
                "critic_name": critic_name,
                "findings": [],
                "error": str(e),
            }

        return {"critic_results": [critic_result]}

    async def reflect_node(state: ReviewState) -> dict:
        """Reflector 验证节点。"""
        return await reflect(state)

    graph = StateGraph(ReviewState)

    graph.add_node("prepare", prepare_node)
    graph.add_node("critic_node", critic_node)
    graph.add_node("aggregate", aggregate)
    graph.add_node("reflect", reflect_node)
    graph.add_node("report", report)

    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", route_to_critics, ["critic_node", "aggregate"])
    graph.add_edge("critic_node", "aggregate")
    graph.add_edge("aggregate", "reflect")
    graph.add_edge("reflect", "report")
    graph.add_edge("report", END)

    return graph.compile()

async def run_review(
    changes: list[dict],
    repo_url: str,
    branch: str,
    mr_iid: int = 0,
    project_id: int = 0,
) -> dict:
    """
    执行完整审查流程。

    参数:
        changes: GitLab MR changes JSON
        repo_url: 仓库 clone 地址
        branch: MR 源分支
        mr_iid: MR 编号
        project_id: GitLab 项目 ID

    返回:
        最终 state（含 risk_score, summary, comments）
    """

    repo_manager = RepoManager()
    try:
        await repo_manager.clone(repo_url, branch)
        logger.info(f"仓库已 clone 到: {repo_manager.clone_path}")

        file_changes = parse_gitlab_changes(changes)

        graph = build_review_graph(repo_manager, file_changes)

        initial_state: ReviewState = {
            "changes": changes,
            "repo_url": repo_url,
            "branch": branch,
            "mr_iid": mr_iid,
            "project_id": project_id,
        }

        result = await graph.ainvoke(initial_state)
        return result

    finally:

        repo_manager.cleanup()
        logger.info("临时仓库已清理")
