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

class Finding(TypedDict, total=False):
    """单个审查发现。"""
    file: str
    line: int
    severity: str
    title: str
    description: str
    suggestion: str
    confidence: float
    critic: str

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

    aggregated_findings: list[Finding]

    verified_findings: list[Finding]

    risk_score: int
    summary: str
    comments: list[dict]
