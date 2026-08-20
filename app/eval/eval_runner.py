"""
Eval Runner — 端到端评测胶水层

把评测数据集与生产 pipeline（run_review）连接起来：

  加载数据集 → 对每个 case 调用 run_review()（与 webhook 生产链路完全相同的入口）
  → run_eval_suite() 计算 P/R/F1 + 收集 calibration_data
  → PlattCalibrator.fit() 训练校准器并保存

用法:
  python -m app.eval.eval_runner \
      --dataset app/eval/aacr_dataset.json \
      --limit 3 \
      --output app/eval/eval_report.json

说明:
  - run_review(changes, repo_url, branch) 三要素直接来自 EvalCase，
    与 webhook.py → _run_review() 的调用方式完全一致
  - mr_iid/project_id 传 0，自动跳过 Checkpoint 机制（评测不需要断点续跑）
  - 单个 case 失败不影响整体评测，按空结果计入（拉低召回率，符合预期）
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.eval.harness import load_dataset, run_eval_suite
from app.graph.builder import run_review

logger = logging.getLogger("eval_runner")


def resolve_repo_url(case, repos_dir: Path | None, offline: bool = True) -> str:
    """
    评测时优先使用本地仓库缓存（从外网准备好、放到 data/aacr_repos 下的副本），
    避免评测时连接 GitHub（内网/离线环境无法访问外网）。

    - 缓存命中：直接返回本地路径，RepoManager 会把它当作 clone 源
      （git 支持从本地路径 clone，sha / 分支检出逻辑同样适用）。
    - 缓存缺失：
        * offline=True（默认，内网场景）：直接抛错，绝不回退到 GitHub
          （连不上会卡死/超时，且内网本就不该走外网）。
        * offline=False（--online）：回退到远程 repo_url（需联网）。

    缓存目录约定: <repos_dir>/<owner>__<name>（与 convert_aacr_bench 一致）
    """
    if repos_dir is None:
        if offline:
            raise RuntimeError(
                "[EvalRunner] 离线模式已开启，但未指定 repos_dir（本地缓存目录），"
                "无法回退到远程 GitHub。请通过 --repos-dir 指定本地仓库目录，"
                "或加 --online 显式允许远程拉取。"
            )
        return case.repo_url

    # case_id 形如 "owner__name_pr123"，去掉 _prXXX 后缀即缓存目录名
    cache_name = case.case_id.rsplit("_pr", 1)[0]
    local_repo = repos_dir / cache_name
    # 命中本地缓存：含 .git 的真实仓库，或纯源码目录（二者都直接按现状使用）
    if (local_repo / ".git").exists() or local_repo.is_dir():
        return str(local_repo.resolve())

    if offline:
        raise FileNotFoundError(
            f"[EvalRunner] 离线模式：{case.case_id} 的本地缓存不存在: {local_repo}\n"
            f"请先从外网把该仓库（停留在目标 commit 状态）准备好并放到该路径，"
            f"目录名须为 '<owner>__<name>'（可含 .git，也可为纯源码目录）。"
        )
    logger.warning(f"[EvalRunner] {case.case_id} 无本地缓存，将走远程: {case.repo_url}")
    return case.repo_url


async def run_eval(
    dataset_path: str,
    limit: int | None = None,
    output_path: str = "app/eval/eval_report.json",
        calibrator_path: str = "app/eval/calibrator.json",
        repos_dir: str | None = "data/aacr_repos",
        offline: bool = True,
) -> dict:
    """
    端到端评测主流程。

    参数:
        dataset_path: 评测数据集路径（convert_aacr_bench.py 的产物）
        limit: 只跑前 N 个 case（调试用）
        output_path: 评测报告输出路径
        calibrator_path: Platt 校准器输出路径
        repos_dir: 本地仓库缓存目录（命中缓存时不走 GitHub；传 None 禁用）
        offline: 是否离线模式（默认 True）。True 时本地缓存缺失直接报错，
            绝不回退到 GitHub（内网/离线环境无法访问外网）；False（--online）
            时允许回退到远程 repo_url。
    """
    cases = load_dataset(dataset_path)
    if limit:
        cases = cases[:limit]
        logger.info(f"限制评测前 {limit} 个 case")

    repos_dir_path = Path(repos_dir) if repos_dir else None

    results_per_case: dict[str, dict] = {}
    errors_per_case: dict[str, str] = {}

    for i, case in enumerate(cases, 1):
        logger.info(
            f"[EvalRunner] ══ [{i}/{len(cases)}] {case.case_id} ══ "
            f"({len(case.changes)} 个变更文件, {len(case.ground_truth)} 条标注)"
        )
        repo_url = resolve_repo_url(case, repos_dir_path, offline=offline)
        try:
            result = await run_review(
                changes=case.changes,
                repo_url=repo_url,
                branch=case.branch,
                mr_iid=0,
                project_id=0,
            )
            results_per_case[case.case_id] = result
            logger.info(
                f"[EvalRunner] {case.case_id} 审查完成 → "
                f"risk={result.get('risk_score', 0)}, comments={len(result.get('comments', []))}"
            )
        except Exception as e:
            logger.error(f"[EvalRunner] {case.case_id} 审查失败: {e}", exc_info=True)
            # 失败按空结果计（计入分母，拉低召回率，符合评测语义）
            results_per_case[case.case_id] = {"comments": [], "risk_score": 0}
            errors_per_case[case.case_id] = str(e)[:200]

    # ── 计算指标 ──
    suite = run_eval_suite(cases, results_per_case)
    m = suite["metrics"]
    logger.info(
        f"[EvalRunner] ══ 评测完成 ══ "
        f"precision={m['precision']}, recall={m['recall']}, f1={m['f1']} "
        f"({m['correct_comments']}/{m['total_comments']} comments 命中, "
        f"ground truth 共 {m['total_ground_truth']} 条)"
    )

    # ── 训练 Platt 校准器（sklearn 可选依赖，缺失时跳过不影响指标）──
    calibrator_fitted = False
    try:
        from app.eval.calibrator import PlattCalibrator
        calibrator = PlattCalibrator()
        calibrator.fit(suite["calibration_data"])
        if calibrator.is_fitted:
            calibrator.save(calibrator_path)
        calibrator_fitted = calibrator.is_fitted
    except ImportError:
        logger.warning("[EvalRunner] 未安装 scikit-learn，跳过 Platt 校准（pip install scikit-learn 后可用）")

    # ── 给 per_case 附上生成的评论明细（含行号）与失败原因 ──
    for case_entry in suite["per_case"]:
        cid = case_entry["case_id"]
        result = results_per_case.get(cid, {})
        case_entry["comments"] = [
            {
                "file": c.get("path") or c.get("file"),
                "line": c.get("line"),
                "severity": c.get("severity"),
                "body": c.get("body"),
            }
            for c in result.get("comments", [])
        ]
        if cid in errors_per_case:
            case_entry["error"] = errors_per_case[cid]

    # ── 保存评测报告 ──
    report = {
        "dataset": dataset_path,
        "metrics": suite["metrics"],
        "per_case": suite["per_case"],
        "calibration_data_count": len(suite["calibration_data"]),
        "calibrator_fitted": calibrator_fitted,
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"[EvalRunner] 评测报告已保存: {output_path}")

    return suite


def main():
    parser = argparse.ArgumentParser(description="devbot 端到端评测")
    parser.add_argument("--dataset", required=True, help="评测数据集路径")
    parser.add_argument("--limit", type=int, default=None, help="只评测前 N 个 case")
    parser.add_argument("--output", default="app/eval/eval_report.json",
                        help="评测报告输出路径")
    parser.add_argument("--calibrator", default="app/eval/calibrator.json",
                        help="Platt 校准器输出路径")
    parser.add_argument("--repos-dir", default="data/aacr_repos",
                        help="本地仓库缓存目录（转换脚本的 --repos-dir），命中缓存时不走 GitHub")
    parser.add_argument("--online", action="store_true", default=False,
                        help="允许本地缓存缺失时回退到远程 GitHub（内网环境请勿使用）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(run_eval(
        dataset_path=args.dataset,
        limit=args.limit,
        output_path=args.output,
        calibrator_path=args.calibrator,
        repos_dir=args.repos_dir,
        offline=not args.online,
    ))


if __name__ == "__main__":
    main()
