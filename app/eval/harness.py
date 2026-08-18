"""
Eval Harness — 评测运行器（与生产链路对齐版）

设计原则：评测的输入格式必须与 webhook 生产链路完全一致。

生产链路（app/gitlab/webhook.py → app/graph/builder.py）：
  data = await request.json()
  changes = await gitlab.get_mr_diff(project_id, mr_iid)
  result = await run_review(
      changes=changes,          # GitLab changes JSON 列表
      repo_url=repo_url,        # agent 工具 clone 的仓库
      branch=source_branch,     # 审查时的代码状态
      mr_iid=..., project_id=..., head_sha=...,
  )

因此评测用例直接存储 changes / repo_url / branch 三要素，
评测时原样传给 run_review()，保证"评测路径 == 生产路径"。

评测流程：
1. 加载评测数据集（N 个 case，每个含 changes + ground truth）
2. 对每个 case 调用 run_review() 完整 pipeline
3. 将返回的 comments 与 ground truth 对比（文件 + 行号区间）
4. 计算精确率、召回率、F1
5. 收集 (confidence, is_correct) 数据对 → 供 Platt 校准使用
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.eval.metrics import compute_metrics, MatchResult

logger = logging.getLogger(__name__)

# report 节点把 confidence 拼在评论正文里: "| confidence: 0.85*"
CONFIDENCE_PATTERN = re.compile(r"confidence:\s*([0-9]*\.?[0-9]+)")


@dataclass
class EvalCase:
    """
    单个评测用例（与 run_review 入参一一对应）。

    changes 格式（与 GitLab get_mr_diff 返回一致）:
    [
      {
        "diff": "@@ -10,6 +10,8 @@\n ...",   # 仅 hunk，无 --- a/ 文件头
        "new_path": "src/login.py",
        "old_path": "src/login.py",
        "new_file": false,
        "deleted_file": false,
        "renamed_file": false
      }
    ]

    ground_truth 格式（人工标注，AACR-Bench 的 is_ai_comment=False 评论）:
    [
      {"file": "src/login.py", "from_line": 12, "to_line": 14,
       "severity": "critical", "title": "未检查 user 是否为 None"}
    ]
    """
    case_id: str
    changes: list[dict]
    repo_url: str
    branch: str                       # AACR 数据集用 target_commit（GitHub 支持按 sha clone）
    ground_truth: list[dict] = field(default_factory=list)


@dataclass
class EvalResult:
    """单个 case 的评测结果。"""
    case_id: str
    comments: list[dict]
    matches: list[MatchResult]
    precision: float
    recall: float
    f1: float
    risk_score: int = 0


def load_dataset(path: str | Path) -> list[EvalCase]:
    """
    加载评测数据集（JSON 数组格式）。

    文件格式：
    [
      {
        "case_id": "owner__repo_pr123",
        "changes": [ {...GitLab change...} ],
        "repo_url": "https://github.com/owner/repo.git",
        "branch": "9484e13c...",
        "ground_truth": [ {"file","from_line","to_line","severity","title"} ]
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
            changes=item["changes"],
            repo_url=item["repo_url"],
            branch=item["branch"],
            ground_truth=item.get("ground_truth", []),
        ))

    logger.info(f"加载评测数据集: {len(cases)} 个用例")
    return cases


def extract_confidence(body: str) -> float:
    """从评论正文中提取 confidence（report 节点拼接格式）。提取失败返回 0.5。"""
    m = CONFIDENCE_PATTERN.search(body or "")
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 0.5


def _file_match(comment_file: str, gt_file: str) -> bool:
    """文件路径匹配：精确相等或互为路径后缀。"""
    if not comment_file or not gt_file:
        return False
    return (
        comment_file == gt_file
        or comment_file.endswith("/" + gt_file)
        or gt_file.endswith("/" + comment_file)
    )


def _line_in_range(line: int, from_line: int, to_line: int, tolerance: int) -> bool:
    """
    行号区间匹配。
    ground truth 标注的是 [from_line, to_line] 闭区间（数据中可能 from > to，需交换），
    comment 行号落在区间外扩 tolerance 行以内视为命中。
    """
    lo, hi = min(from_line, to_line), max(from_line, to_line)
    return (lo - tolerance) <= line <= (hi + tolerance)


def match_comments(
    comments: list[dict],
    ground_truth: list[dict],
    line_tolerance: int = 3,
) -> list[MatchResult]:
    """
    将 run_review 输出的 comments 与 ground truth 匹配。

    匹配规则：
    - 同文件 + 行号落在标注区间（外扩 line_tolerance）内 → 命中
    - 无有效行号（降级为文件级评论）→ 视为未命中（定位失败）
    - 每个 ground truth 最多匹配一条 comment（避免重复计数）
    """
    results = []
    matched_gt_indices: set[int] = set()

    for comment in comments:
        c_file = comment.get("file", "")
        c_line = comment.get("line")
        confidence = extract_confidence(comment.get("body", ""))

        is_correct = False
        has_valid_line = isinstance(c_line, int) and c_line >= 1

        if has_valid_line:
            for i, gt in enumerate(ground_truth):
                if i in matched_gt_indices:
                    continue
                if not _file_match(c_file, gt.get("file", "")):
                    continue
                from_line = gt.get("from_line") or gt.get("line") or 0
                to_line = gt.get("to_line") or from_line
                if _line_in_range(c_line, from_line, to_line, line_tolerance):
                    is_correct = True
                    matched_gt_indices.add(i)
                    break

        results.append(MatchResult(
            comment=comment,
            is_correct=is_correct,
            confidence=confidence,
        ))

    return results


def run_eval_case(case: EvalCase, review_result: dict) -> EvalResult:
    """
    对单个 case 计算评测指标。

    参数:
        case: 评测用例（含 ground_truth）
        review_result: run_review() 的返回值（risk_score/summary/comments）
    """
    comments = review_result.get("comments", [])
    matches = match_comments(comments, case.ground_truth)
    metrics = compute_metrics(matches, total_ground_truth=len(case.ground_truth))

    return EvalResult(
        case_id=case.case_id,
        comments=comments,
        matches=matches,
        precision=metrics["precision"],
        recall=metrics["recall"],
        f1=metrics["f1"],
        risk_score=review_result.get("risk_score", 0),
    )


def run_eval_suite(
    cases: list[EvalCase],
    results_per_case: dict[str, dict],
) -> dict:
    """
    运行完整评测套件。

    参数:
        cases: 评测用例列表
        results_per_case: {case_id: run_review() 返回值}

    返回:
        汇总指标 + 每个 case 的详细结果 + 校准数据
        （calibration_data 供 PlattCalibrator.fit() 训练）
    """
    results = []
    all_matches = []

    for case in cases:
        review_result = results_per_case.get(case.case_id)
        if review_result is None:
            logger.warning(f"[EvalSuite] {case.case_id} 无审查结果，按空结果计")
            review_result = {"comments": [], "risk_score": 0}
        result = run_eval_case(case, review_result)
        results.append(result)
        all_matches.extend(result.matches)

    total_metrics = compute_metrics(
        all_matches,
        total_ground_truth=sum(len(c.ground_truth) for c in cases),
    )

    calibration_data = [
        {"confidence": m.confidence, "is_correct": m.is_correct}
        for m in all_matches
    ]

    return {
        "total_cases": len(cases),
        "total_comments": sum(len(r.comments) for r in results),
        "metrics": total_metrics,
        "per_case": [
            {
                "case_id": r.case_id,
                "precision": r.precision,
                "recall": r.recall,
                "f1": r.f1,
                "risk_score": r.risk_score,
            }
            for r in results
        ],
        "calibration_data": calibration_data,
    }
