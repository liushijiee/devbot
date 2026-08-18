"""
Eval 模块 — 与生产链路对齐的评测体系

组件:
- harness:      评测用例定义（EvalCase）+ 数据集加载 + comments 与 ground truth 匹配
- metrics:      精确率 / 召回率 / F1 计算
- calibrator:   Platt 校准器（修正 Critic 的 confidence 过度自信）
- eval_runner:  端到端评测胶水层（数据集 → run_review → 指标 → 校准器）
- convert_aacr_bench: AACR-Bench 原始数据 → devbot 评测数据集格式转换
"""

