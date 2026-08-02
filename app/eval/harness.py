"""
Eval Harness — 评测运行器
对标注数据集运行审查流程，收集结果，计算指标。

评测流程：
1. 加载评测数据集（N 个 case，每个含 diff + ground truth）
2. 对每个 case 运行 Critic（或完整 pipeline）
3. 将 Critic 输出与 ground truth 对比
4. 计算精确率、召回率、F1
5. 收集 (confidence, is_correct) 数据对 → 供 Platt 校准使用
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.eval.metrics import compute_metrics, MatchResult

logger = logging.getLogger(__name__)


@dataclass
class EvalCase:
    """单个评测用例。"""
    case_id: str
    diff_text: str
    language: str
    ground_truth: list[dict] = field(default_factory=list)


@dataclass
class EvalResult:
    """单个 case 的评测结果。"""
    case_id: str
    findings: list[dict]
    matches: list[MatchResult]
    precision: float
    recall: float
    f1: float


def load_dataset(path: str | Path) -> list[EvalCase]:
    """
    加载评测数据集（JSON 格式）。

    文件格式：
    [
      {
        "case_id": "case_001",
        "diff_text": "@@ -1,3 +1,5 @@...",
        "language": "python",
        "ground_truth": [
          {"file": "src/login.py", "line": 3, "severity": "warning", "title": "未处理 None"}
        ]
      }
    ]
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"评测数据集不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    cases = []
    for item in raw:
        cases.append(EvalCase(
            case_id=item["case_id"],
            diff_text=item["diff_text"],
            language=item.get("language", "python"),
            ground_truth=item.get("ground_truth", []),
        ))

    logger.info(f"加载评测数据集: {len(cases)} 个用例")
    return cases


def match_findings_to_truth(
    findings: list[dict],
    ground_truth: list[dict],
    line_tolerance: int = 3,
) -> list[MatchResult]:
    """
    将 Critic 的 findings 与 ground truth 进行匹配。

    匹配规则：
    - 同文件 + 行号差 ≤ line_tolerance → 视为匹配
    - 每个 ground truth 最多匹配一个 finding（避免重复计数）
    """
    results = []
    matched_gt_indices = set()

    for finding in findings:
        f_file = finding.get("file", "")
        f_line = finding.get("line", 0)
        f_conf = finding.get("confidence", 0.5)

        is_correct = False
        for i, gt in enumerate(ground_truth):
            if i in matched_gt_indices:
                continue
            gt_file = gt.get("file", "")
            gt_line = gt.get("line", 0)

            file_match = (
                f_file == gt_file
                or f_file.endswith("/" + gt_file)
                or gt_file.endswith("/" + f_file)
            )
            line_match = abs(f_line - gt_line) <= line_tolerance

            if file_match and line_match:
                is_correct = True
                matched_gt_indices.add(i)
                break

        results.append(MatchResult(
            finding=finding,
            is_correct=is_correct,
            confidence=f_conf,
        ))

    return results


def run_eval_case(case: EvalCase, findings: list[dict]) -> EvalResult:
    """对单个 case 计算评测指标。"""
    matches = match_findings_to_truth(findings, case.ground_truth)
    metrics = compute_metrics(matches, total_ground_truth=len(case.ground_truth))

    return EvalResult(
        case_id=case.case_id,
        findings=findings,
        matches=matches,
        precision=metrics["precision"],
        recall=metrics["recall"],
        f1=metrics["f1"],
    )


def run_eval_suite(
    cases: list[EvalCase],
    findings_per_case: dict[str, list[dict]],
) -> dict:
    """
    运行完整评测套件。

    参数:
        cases: 评测用例列表
        findings_per_case: {case_id: [findings...]} 每个 case 的 Critic 输出

    返回:
        汇总指标 + 每个 case 的详细结果 + 校准数据
    """
    results = []
    all_matches = []

    for case in cases:
        findings = findings_per_case.get(case.case_id, [])
        result = run_eval_case(case, findings)
        results.append(result)
        all_matches.extend(result.matches)

    total_metrics = compute_metrics(all_matches, total_ground_truth=sum(
        len(c.ground_truth) for c in cases
    ))

    calibration_data = [
        {"confidence": m.confidence, "is_correct": m.is_correct}
        for m in all_matches
    ]

    return {
        "total_cases": len(cases),
        "total_findings": sum(len(r.findings) for r in results),
        "metrics": total_metrics,
        "per_case": [
            {"case_id": r.case_id, "precision": r.precision, "recall": r.recall, "f1": r.f1}
            for r in results
        ],
        "calibration_data": calibration_data,
    }
