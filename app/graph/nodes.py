
import json
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from app.config import get_settings
from app.graph.state import ReviewState, Finding, CriticResult
from app.harness.diff_parser import parse_gitlab_changes, FileChange
from app.harness.file_filter import filter_files
from app.harness.file_grouper import group_files, Bundle
from app.harness.rule_matcher import match_rules
from app.harness.repo_manager import RepoManager
from app.prompts.registry import load_prompt, CRITIC_NAMES
from app.tools.code_tools import create_tools

logger = logging.getLogger(__name__)

def _get_llm(model: str | None = None) -> ChatOpenAI:
    """创建 Qwen LLM 实例（通过 DashScope 兼容 OpenAI 接口）。"""
    settings = get_settings()
    return ChatOpenAI(
        model=model or settings.critic_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.llm_base_url,
        temperature=0.1,
    )

def prepare(state: ReviewState) -> dict:
    """
    Harness 层处理：解析 diff → 过滤 → 分组 → 规则匹配。
    输出供 Critic 使用的结构化数据。
    """

    all_files = parse_gitlab_changes(state["changes"])
    logger.info(f"解析到 {len(all_files)} 个变更文件")

    filtered = filter_files(all_files)
    logger.info(f"过滤后剩余 {len(filtered)} 个文件")

    if not filtered:

        return {
            "diff_text": "",
            "changed_files": "（无需审查的文件）",
            "rules": "",
            "all_file_paths": [],
        }

    bundles = group_files(filtered)
    bundle = bundles[0]
    logger.info(f"分为 {len(bundles)} 个 bundle，当前审查第 1 个（{bundle.total_lines} 行）")

    rules_text = match_rules(bundle.files)

    all_paths = [f.path for f in filtered]
    changed_files_text = "\n".join(f"- {p}" for p in all_paths)

    return {
        "diff_text": bundle.diff_text,
        "changed_files": changed_files_text,
        "rules": rules_text,
        "all_file_paths": all_paths,
    }

async def run_critic(state: ReviewState, critic_name: str, repo_manager: RepoManager,
                     file_changes: list[FileChange]) -> CriticResult:
    """
    运行单个 Critic ReAct Agent。

    参数:
        state: 图状态（包含 diff_text, changed_files, rules）
        critic_name: Critic 名称（correctness/security/performance/quality）
        repo_manager: 仓库管理器（提供 clone_path）
        file_changes: 变更文件列表（供 get_diff_file 工具）
    """
    settings = get_settings()

    try:

        template = load_prompt(critic_name)
        system_prompt = template.system
        user_prompt = template.format_user(
            changed_files=state["changed_files"],
            diff_text=state["diff_text"],
            rules=state["rules"],
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

        return {
            "critic_name": critic_name,
            "findings": findings,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Critic [{critic_name}] 执行失败: {e}")
        return {
            "critic_name": critic_name,
            "findings": [],
            "error": str(e),
        }

def _parse_findings(text: str, critic_name: str) -> list[Finding]:
    """从 LLM 输出中解析 JSON findings。"""

    try:

        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        json_str = text[start:end]
        raw_findings = json.loads(json_str)

        findings = []
        for f in raw_findings:
            f["critic"] = critic_name
            findings.append(f)
        return findings

    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Critic [{critic_name}] 输出解析失败: {e}")
        return []

def aggregate(state: ReviewState) -> dict:
    """
    聚合所有 Critic 的结果：
    1. 合并所有 findings
    2. 按 confidence 阈值过滤
    3. 去重（同文件 + 同行号 + 相似标题）
    """
    settings = get_settings()
    all_findings: list[Finding] = []

    for result in state.get("critic_results", []):
        if result.get("error"):
            logger.warning(f"Critic [{result['critic_name']}] 出错: {result['error']}")
            continue
        all_findings.extend(result.get("findings", []))

    logger.info(f"聚合前共 {len(all_findings)} 个 findings")

    filtered = [f for f in all_findings if f.get("confidence", 0) >= settings.confidence_threshold]

    deduped = _deduplicate(filtered)

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    deduped.sort(key=lambda f: severity_order.get(f.get("severity", "info"), 3))

    logger.info(f"聚合后剩余 {len(deduped)} 个 findings")

    return {"aggregated_findings": deduped}

def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """去重：同文件 + 同行号 + 同 severity 只保留 confidence 最高的。"""
    seen: dict[str, Finding] = {}
    for f in findings:
        key = f"{f.get('file', '')}:{f.get('line', 0)}:{f.get('severity', '')}"
        if key not in seen or f.get("confidence", 0) > seen[key].get("confidence", 0):
            seen[key] = f
    return list(seen.values())

async def reflect(state: ReviewState) -> dict:
    """
    Reflector 后置验证：
    - 对 critical/warning 级别的 findings 进行 LLM 验证
    - info 级别直接通过（节省 token）
    """
    findings = state.get("aggregated_findings", [])
    if not findings:
        return {"verified_findings": []}

    verified = []
    reflector_template = load_prompt("reflector")
    llm = _get_llm()

    for finding in findings:

        if finding.get("severity") == "info":
            verified.append(finding)
            continue

        try:
            user_prompt = reflector_template.format_user(
                diff_text=state.get("diff_text", ""),
                finding=json.dumps(finding, ensure_ascii=False, indent=2),
            )

            response = await llm.ainvoke([
                SystemMessage(content=reflector_template.system),
                HumanMessage(content=user_prompt),
            ])

            verdict = _parse_verdict(response.content)

            if verdict["verdict"] == "reject":
                logger.info(f"Reflector 拒绝: {finding.get('title')} - {verdict['reason']}")
                continue
            elif verdict["verdict"] == "modify" and verdict.get("modified_finding"):
                verified.append(verdict["modified_finding"])
            else:
                verified.append(finding)

        except Exception as e:

            logger.warning(f"Reflector 验证失败: {e}")
            verified.append(finding)

    logger.info(f"Reflector 验证后剩余 {len(verified)} 个 findings")
    return {"verified_findings": verified}

def _parse_verdict(text: str) -> dict:
    """解析 Reflector 的 JSON 输出。"""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return {"verdict": "pass", "reason": "解析失败，默认通过"}
        return json.loads(text[start:end])
    except (json.JSONDecodeError, TypeError):
        return {"verdict": "pass", "reason": "解析失败，默认通过"}

def report(state: ReviewState) -> dict:
    """
    生成最终报告：
    1. 计算风险分（基于 severity 加权）
    2. 生成摘要文本
    3. 构造 GitLab 评论列表
    """
    settings = get_settings()
    findings = state.get("verified_findings", [])

    risk_score = _calculate_risk_score(findings)

    summary = _generate_summary(findings, risk_score)

    comments = []
    for f in findings:
        comments.append({
            "file": f.get("file", ""),
            "line": f.get("line", 0),
            "body": (
                f"**[{f.get('severity', 'info').upper()}]** {f.get('title', '')}\n\n"
                f"{f.get('description', '')}\n\n"
                f"**建议**: {f.get('suggestion', '')}\n\n"
                f"---\n"
                f"*by DevBot ({f.get('critic', 'unknown')} critic) "
                f"| confidence: {f.get('confidence', 0):.2f}*"
            ),
        })

    return {
        "risk_score": risk_score,
        "summary": summary,
        "comments": comments,
    }

def _calculate_risk_score(findings: list[Finding]) -> int:
    """
    风险分计算（0-100）：
    - critical: +30 分/个
    - warning: +15 分/个
    - info: +5 分/个
    - 上限 100
    """
    score = 0
    for f in findings:
        severity = f.get("severity", "info")
        if severity == "critical":
            score += 30
        elif severity == "warning":
            score += 15
        else:
            score += 5
    return min(score, 100)

def _generate_summary(findings: list[Finding], risk_score: int) -> str:
    """生成审查摘要。"""
    if not findings:
        return "✅ 审查完成，未发现问题。"

    critical_count = sum(1 for f in findings if f.get("severity") == "critical")
    warning_count = sum(1 for f in findings if f.get("severity") == "warning")
    info_count = sum(1 for f in findings if f.get("severity") == "info")

    lines = [
        f"## 🔍 DevBot 代码审查报告",
        f"",
        f"**风险分: {risk_score}/100**",
        f"",
        f"| 级别 | 数量 |",
        f"|------|------|",
        f"| 🔴 Critical | {critical_count} |",
        f"| 🟡 Warning | {warning_count} |",
        f"| 🔵 Info | {info_count} |",
        f"",
    ]

    if risk_score >= 70:
        lines.append("⛔ **建议阻断合并**，存在高风险问题需要修复。")
    elif critical_count > 0:
        lines.append("⚠️ 存在 Critical 级别问题，建议修复后合并。")
    else:
        lines.append("✅ 整体风险可控，建议处理后合并。")

    return "\n".join(lines)
