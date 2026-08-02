"""
LangGraph 图结构测试
Mock LLM 调用，验证图的流转逻辑正确。
"""
import sys
import io
import json
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.graph.state import ReviewState, Finding, CriticResult
from app.graph.nodes import prepare, aggregate, report, _parse_findings, _deduplicate

MOCK_CHANGES = [
    {
        "new_path": "src/auth/login.py",
        "old_path": "src/auth/login.py",
        "diff": "@@ -1,3 +1,5 @@\n def login(username, password):\n-    user = query(username)\n+    user = query(username.strip())\n+    if not user:\n+        return None\n     return token(user)",
        "new_file": False,
        "deleted_file": False,
        "renamed_file": False,
    },
    {
        "new_path": "src/routes.py",
        "old_path": "src/routes.py",
        "diff": "@@ -5,2 +5,3 @@\n from auth.login import login\n+from auth.token import refresh",
        "new_file": False,
        "deleted_file": False,
        "renamed_file": False,
    },
]

def test_prepare():
    print("=" * 50)
    print("TEST: prepare 节点（接收预填充数据）")
    print("=" * 50)
    state: ReviewState = {
        "changes": MOCK_CHANGES,
        "repo_url": "https://gitlab.com/test/repo.git",
        "branch": "main",
        "mr_iid": 1,
        "project_id": 100,
        "diff_text": "@@ -1,3 +1,5 @@\n def login(username, password):\n+    if not user:\n+        return None",
        "changed_files": "- src/auth/login.py\n- src/routes.py",
        "rules": "检查异常处理",
        "all_file_paths": ["src/auth/login.py", "src/routes.py"],
    }
    result = prepare(state)
    print(f"  diff_text 长度: {len(result['diff_text'])} 字符")
    print(f"  changed_files:\n{result['changed_files']}")
    print(f"  rules 长度: {len(result['rules'])} 字符")
    assert "src/auth/login.py" in result["changed_files"]
    assert "src/routes.py" in result["changed_files"]
    assert len(result["diff_text"]) > 0
    print("[PASS]\n")

def test_prepare_empty():
    print("=" * 50)
    print("TEST: prepare 节点（无 diff）")
    print("=" * 50)
    state: ReviewState = {
        "changes": [],
        "diff_text": "",
        "changed_files": "",
        "rules": "",
        "all_file_paths": [],
    }
    result = prepare(state)
    assert result["diff_text"] == ""
    assert "无需审查" in result["changed_files"]
    print("  空 diff 正确处理 ✓")
    print("[PASS]\n")

def test_parse_findings():
    print("=" * 50)
    print("TEST: _parse_findings")
    print("=" * 50)

    text = '''经过分析，我发现以下问题：
    [
      {"file": "src/login.py", "line": 3, "severity": "warning", "title": "未处理 None", "description": "test", "suggestion": "fix", "confidence": 0.8}
    ]
    以上是我的发现。'''
    findings = _parse_findings(text, "correctness")
    assert len(findings) == 1
    assert findings[0]["critic"] == "correctness"
    assert findings[0]["severity"] == "warning"
    print(f"  解析到 {len(findings)} 个 findings ✓")

    findings = _parse_findings("代码没有问题。[]", "security")
    assert len(findings) == 0
    print("  空数组解析 ✓")

    findings = _parse_findings("这段代码很好，没有发现问题。", "quality")
    assert len(findings) == 0
    print("  无 JSON 解析 ✓")
    print("[PASS]\n")

def test_aggregate():
    print("=" * 50)
    print("TEST: aggregate 节点")
    print("=" * 50)

    state: ReviewState = {
        "critic_results": [
            {
                "critic_name": "correctness",
                "findings": [
                    {"file": "a.py", "line": 10, "severity": "critical", "title": "bug1", "confidence": 0.9},
                    {"file": "a.py", "line": 20, "severity": "info", "title": "style", "confidence": 0.3},
                ],
                "error": None,
            },
            {
                "critic_name": "security",
                "findings": [
                    {"file": "a.py", "line": 10, "severity": "critical", "title": "bug1-dup", "confidence": 0.7},
                ],
                "error": None,
            },
            {
                "critic_name": "performance",
                "findings": [],
                "error": "timeout",
            },
        ],
    }

    with patch("app.graph.nodes.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(confidence_threshold=0.4)
        result = aggregate(state)

    findings = result["aggregated_findings"]
    print(f"  聚合后: {len(findings)} 个 findings")

    assert len(findings) == 1
    assert findings[0]["confidence"] == 0.9
    print("  低 confidence 过滤 ✓")
    print("  去重（保留高 confidence）✓")
    print("  失败 Critic 跳过 ✓")
    print("[PASS]\n")

def test_report():
    print("=" * 50)
    print("TEST: report 节点")
    print("=" * 50)

    state: ReviewState = {
        "verified_findings": [
            {"file": "a.py", "line": 10, "severity": "critical", "title": "SQL注入", "description": "desc", "suggestion": "fix", "confidence": 0.9, "critic": "security"},
            {"file": "b.py", "line": 5, "severity": "warning", "title": "N+1", "description": "desc", "suggestion": "fix", "confidence": 0.7, "critic": "performance"},
        ],
    }

    with patch("app.graph.nodes.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(risk_block_threshold=70)
        result = report(state)

    print(f"  风险分: {result['risk_score']}")
    print(f"  评论数: {len(result['comments'])}")
    print(f"  摘要前 100 字: {result['summary'][:100]}...")
    assert result["risk_score"] == 45
    assert len(result["comments"]) == 2
    assert "SQL注入" in result["comments"][0]["body"]
    print("[PASS]\n")

def test_report_empty():
    print("=" * 50)
    print("TEST: report（无问题）")
    print("=" * 50)
    state: ReviewState = {"verified_findings": []}
    with patch("app.graph.nodes.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(risk_block_threshold=70)
        result = report(state)
    assert result["risk_score"] == 0
    assert "未发现问题" in result["summary"]
    print(f"  摘要: {result['summary']}")
    print("[PASS]\n")

if __name__ == "__main__":
    test_prepare()
    test_prepare_empty()
    test_parse_findings()
    test_aggregate()
    test_report()
    test_report_empty()

    print("=" * 50)
    print("ALL TESTS PASSED!")
    print("=" * 50)
