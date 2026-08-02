"""
Eval 指标计算
精确率、召回率、F1 + 匹配结果数据结构。
"""

from dataclasses import dataclass


@dataclass
class MatchResult:
    """单个 finding 与 ground truth 的匹配结果。"""
    finding: dict           # Critic 输出的 finding
    is_correct: bool        # 是否匹配到了 ground truth
    confidence: float       # Critic 给出的置信度


def compute_metrics(matches: list[MatchResult], total_ground_truth: int) -> dict:
    """
    计算精确率、召回率、F1。

    精确率 = 正确的 findings / 总 findings（防误报）
    召回率 = 被发现的 ground truth / 总 ground truth（防漏报）
    F1 = 2 * P * R / (P + R)

    参数:
        matches: 每个 finding 的匹配结果
        total_ground_truth: ground truth 总数（用于计算召回率）
    """
    total_findings = len(matches)
    correct_findings = sum(1 for m in matches if m.is_correct)

    precision = correct_findings / total_findings if total_findings > 0 else 0.0
    recall = correct_findings / total_ground_truth if total_ground_truth > 0 else 0.0

    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "total_findings": total_findings,
        "correct_findings": correct_findings,
        "total_ground_truth": total_ground_truth,
    }
