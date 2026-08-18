"""
Eval 指标计算
精确率、召回率、F1 + 匹配结果数据结构。

与生产链路对齐：评测对象是 run_review() 返回的 comments
（即最终发布到 GitLab 的评论），而非中间态 findings。
"""

from dataclasses import dataclass


@dataclass
class MatchResult:
    """单条审查评论与 ground truth 的匹配结果。"""
    comment: dict           # run_review 输出的 comment（file/line/body）
    is_correct: bool        # 是否匹配到了 ground truth
    confidence: float       # 评论正文中提取的置信度（供 Platt 校准）


def compute_metrics(matches: list[MatchResult], total_ground_truth: int) -> dict:
    """
    计算精确率、召回率、F1。

    精确率 = 正确的 comments / 总 comments（防误报）
    召回率 = 被发现的 ground truth / 总 ground truth（防漏报）
    F1 = 2 * P * R / (P + R)

    参数:
        matches: 每条 comment 的匹配结果
        total_ground_truth: ground truth 总数（用于计算召回率）
    """
    total_comments = len(matches)
    correct_comments = sum(1 for m in matches if m.is_correct)

    precision = correct_comments / total_comments if total_comments > 0 else 0.0
    recall = correct_comments / total_ground_truth if total_ground_truth > 0 else 0.0

    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "total_comments": total_comments,
        "correct_comments": correct_comments,
        "total_ground_truth": total_ground_truth,
    }
