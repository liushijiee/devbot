"""
节点输入输出追踪器
用 @trace_node 装饰器包裹每个节点函数，自动将输入/输出写入 logs/pipeline_trace.log。

用法:
    from app.graph.tracer import trace_node

    @trace_node("Prepare")
    def prepare(state):
        ...

    @trace_node("Critic:security")
    async def critic_node(state):
        ...

日志文件位置: 项目根目录/logs/pipeline_trace.log
"""

import asyncio
import dataclasses
import functools
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# ── 日志文件路径 ──
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
TRACE_LOG_FILE = LOG_DIR / "pipeline_trace.log"

# ── 配置 ──
MAX_VALUE_LENGTH = 80000  # 单个字段最大记录字符数
# 这些字段包含多行文本，日志中真实换行显示（不转义）
MULTILINE_FIELDS = {"diff_text", "changed_files", "rules", "summary", "content"}


def _ensure_log_dir():
    """确保 logs 目录存在。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _to_serializable(value: Any) -> Any:
    """
    将任意值转为 JSON 可序列化的原生 Python 对象（不做字符串化）。
    最终只 json.dumps 一次，不会产生双重转义。
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_VALUE_LENGTH:
            return value[:MAX_VALUE_LENGTH] + f"\n... (截断, 总长{len(value)}字符)"
        return value
    if isinstance(value, dict):
        return {k: _to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return str(value)


def _format_multiline(text: str) -> str:
    """多行文本格式化：真实换行 + 行号，方便日志阅读。"""
    if len(text) > MAX_VALUE_LENGTH:
        text = text[:MAX_VALUE_LENGTH] + f"\n... (截断, 总长{len(text)}字符)"
    lines = text.split("\n")
    numbered = [f"  {i+1:4d} │ {line}" for i, line in enumerate(lines)]
    return "\n".join(numbered)


def _format_value_lines(key: str, value: Any) -> list[str]:
    """
    将一个 key-value 格式化为日志行列表。
    多行文本字段真实换行+行号；其他字段 JSON 缩进展示。
    """
    lines = []
    if isinstance(value, str) and "\n" in value and key in MULTILINE_FIELDS:
        lines.append(f"│ {key}:")
        for line in _format_multiline(value).split("\n"):
            lines.append(f"│   {line}")
    else:
        try:
            formatted = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            formatted = str(value)
        formatted_lines = formatted.split("\n")
        if len(formatted_lines) == 1:
            lines.append(f"│ {key}: {formatted_lines[0]}")
        else:
            lines.append(f"│ {key}:")
            for fl in formatted_lines:
                lines.append(f"│   {fl}")
    return lines


def _write_trace(node_name: str, phase: str, data: dict):
    """
    写入一条追踪记录到日志文件。
    每个顶层 key 独立一段，多行文本真实换行，其他字段 JSON 缩进。
    """
    _ensure_log_dir()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    separator = "─" * 60

    lines = [
        f"\n┌{separator}",
        f"│ [{timestamp}] 节点: {node_name} | 阶段: {phase}",
        f"│",
    ]

    for k, v in data.items():
        lines.extend(_format_value_lines(k, v))
        lines.append(f"│")

    lines.append(f"└{separator}")

    with open(TRACE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def trace_node(node_name: str):
    """
    装饰器：自动记录节点的输入和输出到 logs/pipeline_trace.log。

    支持同步和异步函数。

    参数:
        node_name: 节点显示名称，如 "Prepare", "Critic:security", "Report"

    用法:
        @trace_node("Prepare")
        def prepare(state):
            ...

        @trace_node("Reflect")
        async def reflect(state):
            ...
    """
    def decorator(func: Callable) -> Callable:

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                input_data = _build_input_record(args, kwargs)
                _write_trace(node_name, "INPUT", input_data)

                try:
                    result = await func(*args, **kwargs)
                except Exception as e:
                    _write_trace(node_name, "ERROR", {"exception": str(e)})
                    raise

                output_data = {"result": _to_serializable(result)}
                _write_trace(node_name, "OUTPUT", output_data)
                return result

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                input_data = _build_input_record(args, kwargs)
                _write_trace(node_name, "INPUT", input_data)

                try:
                    result = func(*args, **kwargs)
                except Exception as e:
                    _write_trace(node_name, "ERROR", {"exception": str(e)})
                    raise

                output_data = {"result": _to_serializable(result)}
                _write_trace(node_name, "OUTPUT", output_data)
                return result

            return sync_wrapper

    return decorator


def _build_input_record(args: tuple, kwargs: dict) -> dict:
    """
    构建输入记录。
    单参数直接展开（dict 展开为字段，list 直接展示）；
    多参数用 arg_0, arg_1 ... 命名。
    """
    record = {}
    if len(args) == 1 and not kwargs:
        # 单参数：直接展开，不包裹
        record = _to_serializable(args[0])
        # 如果结果不是 dict（比如是 list），包一层 result
        if not isinstance(record, dict):
            record = {"result": record}
    else:
        # 多参数：逐个命名
        for i, arg in enumerate(args):
            record[f"arg_{i}"] = _to_serializable(arg)
        for k, v in kwargs.items():
            record[k] = _to_serializable(v)
    return record
