"""
AACR-Bench → devbot EvalCase 数据集转换脚本

数据来源: https://github.com/alibaba/aacr-bench
          https://huggingface.co/datasets/Alibaba-Aone/aacr-bench

AACR-Bench 原始数据是一个 JSON 数组，每条样本包含:
  - githubPrUrl / source_commit / target_commit / project_main_language
  - comments[]: 人工 + AI 混合标注的评论(is_ai_comment 区分)

本脚本将其转换为 harness.load_dataset() 可加载的格式:
  [{"case_id", "diff_text", "language", "ground_truth": [...]}]

用法:
  python -m app.eval.convert_aacr_bench \
      --input path/to/positive_samples.json \
      --output app/eval/aacr_dataset.json \
      --repos-dir data/aacr_repos \
      --language Python --limit 20

注意:
  1. diff 需通过 clone 原仓库执行 `git diff source..target` 动态生成
  2. ground truth 只取 is_ai_comment=False 的人工标注评论
  3. category → severity 映射见 CATEGORY_SEVERITY_MAP
"""

import argparse
import json
import logging
import random
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("convert_aacr_bench")

# AACR-Bench category → devbot severity
CATEGORY_SEVERITY_MAP = {
    "Security": "critical",
    "Defect": "critical",
    "Maintainability": "warning",
    "Performance": "warning",
}

DEFAULT_SEVERITY = "warning"

# githubPrUrl 形如 https://github.com/psf/requests/pull/5711
PR_URL_PATTERN = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def parse_pr_url(url: str) -> tuple[str, str] | None:
    """从 PR 链接解析 owner/name。"""
    m = PR_URL_PATTERN.search(url or "")
    if not m:
        return None
    return m.group(1), m.group(2)


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ensure_repo(owner: str, name: str, repos_dir: Path) -> Path | None:
    """clone 仓库(带缓存)，确保能拿到任意 commit。"""
    repo_dir = repos_dir / f"{owner}__{name}"
    clone_url = f"https://github.com/{owner}/{name}.git"

    if not repo_dir.exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"cloning {clone_url} ...")
        # --filter=blob:none 减少下载体积，按需拉取文件内容
        result = subprocess.run(
            ["git", "clone", "--filter=blob:none", clone_url, str(repo_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            logger.error(f"clone 失败 {clone_url}: {result.stderr.strip()}")
            return None
    return repo_dir


def get_diff(repo_dir: Path, source_commit: str, target_commit: str) -> str | None:
    """生成 base..head 的 diff 文本；commit 缺失时尝试按 sha fetch。"""
    result = run_git(["diff", f"{source_commit}..{target_commit}"], repo_dir)
    if result.returncode != 0:
        # PR 的 head commit 可能不在默认分支上，显式 fetch
        for sha in (source_commit, target_commit):
            run_git(["fetch", "origin", sha], repo_dir)
        result = run_git(["diff", f"{source_commit}..{target_commit}"], repo_dir)
        if result.returncode != 0:
            logger.error(
                f"git diff 失败 {repo_dir.name}: {result.stderr.strip()[:200]}"
            )
            return None
    return result.stdout


def record_to_case(record: dict, repos_dir: Path) -> dict | None:
    """将一条 AACR-Bench 记录转换为一个 EvalCase dict；失败返回 None。"""
    pr_url = record.get("githubPrUrl", "")
    parsed = parse_pr_url(pr_url)
    if not parsed:
        logger.warning(f"无法解析 PR 链接: {pr_url}")
        return None
    owner, name = parsed

    # 只保留人工标注的评论作为 ground truth
    human_comments = [
        c for c in record.get("comments", [])
        if not c.get("is_ai_comment", True)
    ]
    if not human_comments:
        return None

    repo_dir = ensure_repo(owner, name, repos_dir)
    if repo_dir is None:
        return None

    diff_text = get_diff(
        repo_dir,
        record.get("source_commit", ""),
        record.get("target_commit", ""),
    )
    if not diff_text:
        return None

    ground_truth = []
    for c in human_comments:
        category = c.get("category", "")
        ground_truth.append({
            "file": c.get("path", ""),
            "line": c.get("from_line") or 0,
            "severity": CATEGORY_SEVERITY_MAP.get(category, DEFAULT_SEVERITY),
            "title": (c.get("note") or "").strip().split("\n")[0][:200],
        })

    pr_no = PR_URL_PATTERN.search(pr_url).group(3)
    return {
        "case_id": f"{owner}__{name}_pr{pr_no}",
        "diff_text": diff_text,
        "language": (record.get("project_main_language") or "python").lower(),
        "ground_truth": ground_truth,
    }


def convert(input_path: Path, output_path: Path, repos_dir: Path,
            language: str | None, limit: int | None, seed: int) -> None:
    with open(input_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    logger.info(f"加载 AACR-Bench 原始数据: {len(raw)} 条")

    if language:
        raw = [r for r in raw
               if (r.get("project_main_language") or "").lower() == language.lower()]
        logger.info(f"按语言 {language} 过滤后: {len(raw)} 条")

    if limit:
        rng = random.Random(seed)
        rng.shuffle(raw)
        raw = raw[:limit]
        logger.info(f"随机采样 {limit} 条 (seed={seed})")

    cases = []
    for i, record in enumerate(raw, 1):
        logger.info(f"[{i}/{len(raw)}] 转换 {record.get('githubPrUrl', '')}")
        case = record_to_case(record, repos_dir)
        if case:
            cases.append(case)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    logger.info(f"完成: {len(cases)}/{len(raw)} 条转换成功 → {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AACR-Bench → devbot EvalCase 转换")
    parser.add_argument("--input", required=True, help="AACR-Bench 原始 JSON 文件路径")
    parser.add_argument("--output", default="app/eval/aacr_dataset.json",
                        help="输出数据集路径 (load_dataset 可直接加载)")
    parser.add_argument("--repos-dir", default="data/aacr_repos",
                        help="原仓库 clone 缓存目录")
    parser.add_argument("--language", default=None,
                        help="仅保留指定语言 (如 Python)")
    parser.add_argument("--limit", type=int, default=None, help="随机采样条数")
    parser.add_argument("--seed", type=int, default=42, help="采样随机种子")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(
            f"原始数据文件不存在: {input_path}\n"
            "请先从 https://huggingface.co/datasets/Alibaba-Aone/aacr-bench 下载"
        )
        sys.exit(1)

    convert(input_path, Path(args.output), Path(args.repos_dir),
            args.language, args.limit, args.seed)


if __name__ == "__main__":
    main()
