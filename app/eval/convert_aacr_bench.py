"""
AACR-Bench → devbot EvalCase 数据集转换脚本

数据来源: https://github.com/alibaba/aacr-bench
          https://huggingface.co/datasets/Alibaba-Aone/aacr-bench

AACR-Bench 原始数据是一个 JSON 数组，每条样本包含:
  - githubPrUrl / source_commit / target_commit / project_main_language
  - comments[]: 人工 + AI 混合标注的评论(is_ai_comment 区分)

本脚本将其转换为 harness.load_dataset() 可加载的格式（与生产链路对齐）:
  [{
    "case_id", 
    "changes": [GitLab changes JSON，与 get_mr_diff 返回一致],
    "repo_url", "branch"(= target_commit),
    "ground_truth": [{"file","from_line","to_line","severity","title"}]
  }]

用法:
  python -m app.eval.convert_aacr_bench \
      --input path/to/positive_samples.json \
      --output app/eval/aacr_dataset.json \
      --repos-dir data/aacr_repos \
      --language Python --limit 20

注意:
  1. diff 需通过 clone 原仓库执行 `git diff source..target` 动态生成，
     再按文件切分为 GitLab changes 格式（diff 字段只保留 hunk，去掉 --- a/ 文件头）
  2. positive_samples.json 中的评论（无论 AI 还是人工产出）均已通过
     80+ 专家三轮交叉验证，默认全部作为 ground truth（与官方转换器一致）；
     is_ai_comment 只是"来源"标记（source_model 记录产出模型），不是置信度
  3. category → severity 映射见 CATEGORY_SEVERITY_MAP
  4. branch 字段存 target_commit：GitHub 支持按任意 sha clone，
     使评测时 agent 看到的代码状态与 PR 被审查时完全一致
"""

import argparse
import json
import logging
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("convert_aacr_bench")

# AACR-Bench category 实际取值 → devbot severity
CATEGORY_SEVERITY_MAP = {
    "Security Vulnerability": "critical",
    "Code Defect": "critical",
    "Performance": "warning",
    "Maintainability and Readability": "warning",
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
    """clone 仓库(带缓存+自动重试)，确保能拿到任意 commit。"""
    repo_dir = repos_dir / f"{owner}__{name}"
    clone_url = f"https://github.com/{owner}/{name}.git"

    if repo_dir.exists():
        return repo_dir

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"cloning {clone_url} ...")
    # --depth=1: 浅克隆只拉一个 commit 的历史，但文件内容完整下载。
    # 不用 --filter=blob:none：blob 缺失会导致该缓存无法作为评测时的本地
    # clone 源（eval_runner --repos-dir），文件内容完整性是硬要求
    result = subprocess.run(
        ["git", "clone", "--depth=1", clone_url, str(repo_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        logger.error(f"clone 失败 {clone_url}: {result.stderr.strip()}")
        shutil.rmtree(repo_dir, ignore_errors=True)  # 清理残缺目录，避免下次误判已缓存
        return None
    return repo_dir


def get_diff(repo_dir: Path, source_commit: str, target_commit: str) -> str | None:
    """生成 base..head 的 diff 文本；commit 缺失时逐级补齐。"""
    result = run_git(["diff", f"{source_commit}..{target_commit}"], repo_dir)
    if result.returncode != 0:
        # PR 的 head commit 可能不在默认分支上，显式按 sha fetch
        for sha in (source_commit, target_commit):
            run_git(["fetch", "origin", sha], repo_dir)
        result = run_git(["diff", f"{source_commit}..{target_commit}"], repo_dir)
    if result.returncode != 0:
        # 浅克隆可能导致 commit 图不完整，解除浅克隆后重试
        run_git(["fetch", "--unshallow", "origin"], repo_dir)
        result = run_git(["diff", f"{source_commit}..{target_commit}"], repo_dir)
    if result.returncode != 0:
        logger.error(
            f"git diff 失败 {repo_dir.name}: {result.stderr.strip()[:200]}"
        )
        return None
    return result.stdout


def split_unified_diff_to_changes(diff_text: str) -> list[dict]:
    """
    将 `git diff` 的完整输出切分为 GitLab changes 格式的条目列表。

    与 app/gitlab/client.get_mr_diff() 的返回对齐：
    - diff 字段只保留 hunk 内容（去掉 "--- a/xxx" "+++ b/xxx" 文件头）
    - 附带 new_path/old_path/new_file/deleted_file/renamed_file 元信息

    parse_gitlab_changes() 可直接消费该结构。
    """
    changes = []
    sections = re.split(r"^diff --git ", diff_text, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue
        lines = section.split("\n")

        # 首行: "a/<old_path> b/<new_path>"
        header_match = re.match(r"a/(.+?) b/(.+)$", lines[0])
        if not header_match:
            continue
        old_path, new_path = header_match.group(1), header_match.group(2)

        is_new = is_deleted = False
        hunk_lines = []
        for line in lines[1:]:
            if line.startswith("@@"):
                hunk_lines.append(line)
            elif hunk_lines:
                # 已进入 hunk，后续行全部保留
                hunk_lines.append(line)
            elif line.startswith("--- "):
                is_new = line[4:].strip() == "/dev/null"
            elif line.startswith("+++ "):
                is_deleted = line[4:].strip() == "/dev/null"

        if not hunk_lines:
            continue

        changes.append({
            "old_path": old_path,
            "new_path": new_path,
            "diff": "\n".join(hunk_lines),
            "new_file": is_new,
            "deleted_file": is_deleted,
            "renamed_file": old_path != new_path,
        })

    return changes


def record_to_case(record: dict, repos_dir: Path, human_only: bool = False) -> dict | None:
    """将一条 AACR-Bench 记录转换为一个 EvalCase dict；失败返回 None。"""
    pr_url = record.get("githubPrUrl", "")
    parsed = parse_pr_url(pr_url)
    if not parsed:
        logger.warning(f"无法解析 PR 链接: {pr_url}")
        return None
    owner, name = parsed

    # positive_samples 中的评论均已通过专家验证，默认全部作为 ground truth；
    # human_only=True 时只保留人工产出的评论（更严格但更稀疏，不推荐）
    comments = record.get("comments", [])
    if human_only:
        comments = [c for c in comments if not c.get("is_ai_comment", True)]
    if not comments:
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

    changes = split_unified_diff_to_changes(diff_text)
    if not changes:
        logger.warning(f"diff 切分结果为空: {pr_url}")
        return None

    ground_truth = []
    for c in comments:
        if not (c.get("note") or "").strip():
            continue  # 个别评论无正文，无法作为标注
        category = c.get("category", "")
        from_line = c.get("from_line") or 0
        to_line = c.get("to_line") or from_line
        ground_truth.append({
            "file": c.get("path", ""),
            "from_line": from_line,
            "to_line": to_line,
            "severity": CATEGORY_SEVERITY_MAP.get(category, DEFAULT_SEVERITY),
            "title": (c.get("note") or "").strip().split("\n")[0][:200],
        })

    pr_no = PR_URL_PATTERN.search(pr_url).group(3)
    return {
        "case_id": f"{owner}__{name}_pr{pr_no}",
        "changes": changes,
        "repo_url": f"https://github.com/{owner}/{name}.git",
        # branch 存 target_commit：评测时按 PR 被审查时的代码状态 clone
        "branch": record.get("target_commit", ""),
        "language": (record.get("project_main_language") or "python").lower(),
        "ground_truth": ground_truth,
    }


def convert(input_path: Path, output_path: Path, repos_dir: Path,
            language: str | None, limit: int | None, seed: int,
            human_only: bool = False) -> None:
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
        case = record_to_case(record, repos_dir, human_only)
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
    parser.add_argument("--human-only", action="store_true",
                        help="只保留人工产出的评论作为 ground truth（默认保留全部已验证评论）")
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
            args.language, args.limit, args.seed, args.human_only)


if __name__ == "__main__":
    main()
