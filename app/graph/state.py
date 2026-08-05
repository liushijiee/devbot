"""
LangGraph 状态定义
State 是图中所有节点共享的数据结构，每个节点读取 + 修改 State。

设计意图：
- 输入字段：Webhook 传入的原始数据
- 中间字段：各节点产出的中间结果
- 输出字段：最终审查报告
"""

import operator
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict

def _merge_token_usage(a: dict, b: dict) -> dict:
    """合并两个 token_usage dict（用于并行 Critic 结果归集）。"""
    if not a:
        return b
    if not b:
        return a
    return {
        "input_tokens": a.get("input_tokens", 0) + b.get("input_tokens", 0),
        "output_tokens": a.get("output_tokens", 0) + b.get("output_tokens", 0),
        "llm_calls": a.get("llm_calls", 0) + b.get("llm_calls", 0),
    }

class Finding(TypedDict, total=False):
    """单个审查发现。"""
    file: str
    line: int
    existing_code: str
    severity: str
    title: str
    description: str
    suggestion: str
    confidence: float
    critic: str

class TokenUsage(TypedDict):
    """Token 消耗统计。"""
    input_tokens: int
    output_tokens: int
    llm_calls: int

class CriticResult(TypedDict):
    """单个 Critic 的完整输出。"""
    critic_name: str
    findings: list[Finding]
    error: Optional[str]

class ReviewState(TypedDict, total=False):
    """
    图的全局状态。

    字段分三组：
    1. 输入（Webhook 传入）
    2. 中间产物（各节点生成）
    3. 输出（最终报告）
    """

    changes: list[dict]
    repo_url: str
    branch: str
    mr_iid: int
    project_id: int

    diff_text: str
    changed_files: str
    rules: str
    all_file_paths: list[str]

    critic_results: Annotated[list[CriticResult], operator.add]

    token_usage: Annotated[dict, _merge_token_usage]

    aggregated_findings: list[Finding]

    verified_findings: list[Finding]

    risk_score: int
    summary: str
    comments: list[dict]
