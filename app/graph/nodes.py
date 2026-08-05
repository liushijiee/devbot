"""
LangGraph 节点实现
每个节点是图中的一个处理步骤。

节点列表：
- prepare: Harness 层处理（格式化 bundle 数据供 Critic 使用）
- aggregate: 合并去重所有 Critic 的 findings
- reflect: Reflector 验证 Agent（带工具，独立调查）
- report: 计算风险分 + 生成输出
"""


import json
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from app.config import get_settings
from app.graph.state import ReviewState, Finding, CriticResult, TokenUsage
from app.harness.diff_parser import parse_gitlab_changes, FileChange
from app.harness.file_filter import filter_files
from app.harness.file_grouper import group_files, Bundle
from app.harness.rule_matcher import match_rules
from app.harness.repo_manager import RepoManager
from app.prompts.registry import load_prompt, CRITIC_NAMES
from app.tools.code_tools import create_tools
from app.graph.tracer import trace_node

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

def _extract_token_usage(messages: list) -> TokenUsage:
    """从 LangGraph agent 的 messages 中提取 token 用量。"""
    usage: TokenUsage = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}
    for msg in messages:
        metadata = getattr(msg, "response_metadata", {}) or {}
        token_usage = metadata.get("token_usage", {})
        if token_usage:
            usage["input_tokens"] += token_usage.get("prompt_tokens", 0)
            usage["output_tokens"] += token_usage.get("completion_tokens", 0)
            usage["llm_calls"] += 1
    return usage

@trace_node("node1. prepare")
def prepare(state: ReviewState) -> dict:
    """
    Harness 层处理：格式化 bundle 数据供 Critic 使用。
    输入 state 中已包含 diff_text / changed_files / rules（由 run_review 预填充）。
    此节点做最终校验和补充。
    """
    logger.info("[Prepare] ══ 开始 Harness 层处理 ══")

    diff_text = state.get("diff_text", "")
    changed_files = state.get("changed_files", "")
    rules = state.get("rules", "")
    all_file_paths = state.get("all_file_paths", [])

    if not diff_text:
        logger.info("[Prepare] 无 diff 内容，跳过审查")
        return {
            "diff_text": "",
            "changed_files": "（无需审查的文件）",
            "rules": "",
            "all_file_paths": [],
        }

    logger.info(f"[Prepare] ══ 完成 ══ diff={len(diff_text)}字符, 文件={len(all_file_paths)}, 规则={len(rules)}字符")
    return {
        "diff_text": diff_text,
        "changed_files": changed_files,
        "rules": rules,
        "all_file_paths": all_file_paths,
    }


@trace_node("从LLM输出中解析文件diff结果. _parse_findings")
def _parse_findings(text: str, critic_name: str) -> list[Finding]:
    """从 LLM 输出中解析 JSON findings。"""

    try:

        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            logger.debug(f"[Parse] {critic_name}: 未找到 JSON 数组")
            return []
        json_str = text[start:end]
        raw_findings = json.loads(json_str)

        findings = []
        for f in raw_findings:
            f["critic"] = critic_name
            findings.append(f)
        logger.debug(f"[Parse] {critic_name}: 解析出 {len(findings)} 个 findings")
        return findings

    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"[Parse] {critic_name}: JSON 解析失败: {e}")
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

    logger.info("[Aggregate] ══ 开始聚合 ══")
    for result in state.get("critic_results", []):
        if result.get("error"):
            logger.warning(f"[Aggregate]   ✗ {result['critic_name']}: 出错 - {result['error']}")
            continue
        count = len(result.get("findings", []))
        logger.debug(f"[Aggregate]   ✓ {result['critic_name']}: {count} 个 findings")
        all_findings.extend(result.get("findings", []))

    logger.info(f"[Aggregate] 合并后共 {len(all_findings)} 个 findings")

    filtered = [f for f in all_findings if f.get("confidence", 0) >= settings.confidence_threshold]
    logger.info(f"[Aggregate] confidence >= {settings.confidence_threshold} 过滤后: {len(filtered)} 个")

    deduped = _deduplicate(filtered)
    logger.debug(f"[Aggregate] 去重后: {len(deduped)} 个")

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    deduped.sort(key=lambda f: severity_order.get(f.get("severity", "info"), 3))

    for f in deduped:
        logger.debug(f"[Aggregate]   [{f.get('severity','?')}] {f.get('file','?')}:{f.get('line',0)} - {f.get('title','?')} (conf={f.get('confidence',0):.2f})")

    logger.info(f"[Aggregate] ══ 完成 ══ 最终 {len(deduped)} 个 findings")
    return {"aggregated_findings": deduped}

@trace_node("6. _deduplicate")
def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """去重：同文件 + 同行号 + 同 severity 只保留 confidence 最高的。"""
    seen: dict[str, Finding] = {}
    for f in findings:
        key = f"{f.get('file', '')}:{f.get('line', 0)}:{f.get('severity', '')}"
        if key not in seen or f.get("confidence", 0) > seen[key].get("confidence", 0):
            seen[key] = f
    return list(seen.values())

@trace_node("7. reflect")
async def reflect(state: ReviewState, repo_manager: RepoManager,
                  file_changes: list[FileChange]) -> dict:
    """
    Reflector 验证 Agent（带工具）：
    - 对 critical/warning 级别的 findings 进行独立调查验证
    - 可调用 read_file / grep / get_diff_file 获取真实代码上下文
    - info 级别直接通过（节省 token）

    与旧版区别：
    - 旧版：只看 diff + finding 文本做判断（Critic 幻觉时无法识别）
    - 新版：能主动读取代码验证声明是否属实（独立审计员）
    """
    findings = state.get("aggregated_findings", [])
    if not findings:
        logger.info("[Reflect] 无 findings，跳过验证")
        return {"verified_findings": [], "reflect_token_usage": {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}}

    settings = get_settings()
    logger.info(f"[Reflect] ══ 开始验证 {len(findings)} 个 findings（工具增强模式）══")
    verified = []
    reflector_template = load_prompt("reflector")

    tools = create_tools(repo_manager, file_changes)
    llm = _get_llm()

    reflect_usage: TokenUsage = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}

    for i, finding in enumerate(findings, 1):

        if finding.get("severity") == "info":
            logger.debug(f"[Reflect]   {i}/{len(findings)} [info] 直接通过: {finding.get('title','')}")
            verified.append(finding)
            continue

        try:
            user_prompt = reflector_template.format_user(
                diff_text=state.get("diff_text", ""),
                finding=json.dumps(finding, ensure_ascii=False, indent=2),
            )

            agent = create_react_agent(
                model=llm,
                tools=tools,
                prompt=SystemMessage(content=reflector_template.system),
            )

            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=user_prompt)]},
                config={"recursion_limit": 8},
            )

            # 统计本次验证的 token 消耗
            usage = _extract_token_usage(result["messages"])
            reflect_usage["input_tokens"] += usage["input_tokens"]
            reflect_usage["output_tokens"] += usage["output_tokens"]
            reflect_usage["llm_calls"] += usage["llm_calls"]

            last_msg = result["messages"][-1].content
            verdict = _parse_verdict(last_msg)

            if verdict["verdict"] == "reject":
                logger.info(f"[Reflect]   {i}/{len(findings)} ✗ 拒绝: {finding.get('title')} - {verdict['reason']}")
                continue
            elif verdict["verdict"] == "modify" and verdict.get("modified_finding"):
                logger.info(f"[Reflect]   {i}/{len(findings)} ✏ 修改: {finding.get('title')}")
                verified.append(verdict["modified_finding"])
            else:
                logger.debug(f"[Reflect]   {i}/{len(findings)} ✓ 通过: {finding.get('title')}")
                verified.append(finding)

        except Exception as e:
            logger.warning(f"[Reflect]   {i}/{len(findings)} 验证异常，默认通过: {e}")
            verified.append(finding)

    logger.info(
        f"[Reflect] ══ 完成 ══ {len(findings)} → {len(verified)} 个 findings"
        f" | token: in={reflect_usage['input_tokens']}, out={reflect_usage['output_tokens']}, calls={reflect_usage['llm_calls']}"
    )
    return {"verified_findings": verified, "reflect_token_usage": reflect_usage}

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

@trace_node("8. report")
def report(state: ReviewState) -> dict:
    """
    生成最终报告：
    1. 计算风险分（基于 severity 加权）
    2. 生成摘要文本
    3. 构造 GitLab 评论列表
    """
    settings = get_settings()
    findings = state.get("verified_findings", [])

    logger.info(f"[Report] ══ 生成报告 ══ ({len(findings)} 个 findings)")
    risk_score = _calculate_risk_score(findings)
    logger.info(f"[Report] 风险分: {risk_score}/100")

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
