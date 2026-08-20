# Eval 模块使用手册

对 AACR-Bench 真实 PR 数据运行完整审查 pipeline（与 webhook 生产链路完全相同的 `run_review()` 入口），计算 P/R/F1 并训练 Platt 校准器。

> 所有命令均在 `devbot/devbot/` 目录下执行（即 `app/` 所在目录），使用 conda devbot 环境。

## 0. 激活环境

```powershell
cd C:\Users\46731\Desktop\devbot\devbot
conda activate devbot
```

## 1. 转换 AACR-Bench 数据集

将 AACR-Bench 原始数据转成 devbot 评测格式（`changes` + `repo_url` + `branch` 三要素）。

```powershell
# 全量转换 Python 子集（21 个 PR）
python -m app.eval.convert_aacr_bench `
  --input C:\Users\46731\Desktop\aacr\aacr-bench\dataset\positive_samples.json `
  --output app/eval/aacr_dataset.json `
  --language Python

# 小规模试跑：随机采样 3 条
python -m app.eval.convert_aacr_bench `
  --input C:\Users\46731\Desktop\aacr\aacr-bench\dataset\positive_samples.json `
  --output app/eval/aacr_dataset_test.json `
  --language Python --limit 3 --seed 42
```

### 转换脚本参数

| 参数 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `--input` | 必填 | AACR-Bench 原始 JSON 路径 |
| `--output` | `app/eval/aacr_dataset.json` | 输出数据集路径 |
| `--repos-dir` | `data/aacr_repos` | 原仓库 clone 缓存目录（有缓存，重跑不重复 clone） |
| `--language` | 全部 | 只保留指定语言（如 `Python`） |
| `--limit` | 全量 | 随机采样条数 |
| `--seed` | 42 | 采样随机种子（保证子集可复现） |
| `--human-only` | 关 | 只保留人工产出的评论作为 ground truth（默认保留全部专家验证通过的评论，与官方一致） |

> 首次转换会 clone 多个 GitHub 大仓库，可能较慢；失败后直接重跑即可，已成功的仓库走缓存。

## 2. 运行端到端评测

```powershell
# 先跑 2 条验证流程（会真实调用 LLM，注意 token 消耗）
python -m app.eval.eval_runner --dataset app/eval/aacr_dataset.json --limit 2

# 全量评测
python -m app.eval.eval_runner --dataset app/eval/aacr_dataset.json

# 自定义输出路径
python -m app.eval.eval_runner `
  --dataset app/eval/aacr_dataset_test.json `
  --output app/eval/eval_report.json `
  --calibrator app/eval/calibrator.json
```

### eval_runner 参数

| 参数 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `--dataset` | 必填 | 转换脚本产出的数据集路径 |
| `--limit` | 全量 | 只评测前 N 个 case |
| `--output` | `app/eval/eval_report.json` | 评测报告输出路径 |
| `--calibrator` | `app/eval/calibrator.json` | Platt 校准器输出路径 |

## 3. 产出文件说明

| 文件 | 内容 |
| ---- | ---- |
| `eval_report.json` | 总体 P/R/F1 + 每个 case 的明细 + 校准数据统计 |
| `calibrator.json` | Platt 校准器参数（confidence → 真实正确率的映射），需 ≥5 条校准数据且正负样本都有才会生成 |

## 4. 常见问题

**Q: 评测会把评论发到 GitHub/GitLab 的 PR 上吗？**
不会。评测只调用 `run_review()`（纯计算），发评论的逻辑在 `webhook.py` 层，评测链路不经过；且 `mr_iid=0/project_id=0` 是无效 ID。

**Q: 为什么有的 PR 转换时被跳过？**
diff 拉取失败（网络超时）或无有效评论。直接重跑，仓库有缓存。

**Q: 评测成本怎么控制？**
每个 case = 4 个 Critic + Reflector 的完整 LLM 调用。先用 `--limit 2` 估算单 case token 消耗，再决定全量。

**Q: 想要纯人工标注的严格子集？**
转换时加 `--human-only`（ground truth 会从约 2145 条缩到 391 条，更稀疏，一般不推荐）。

**Q: 校准器没生成？**
calibration_data 不足 5 条或全部同对/同错时无法拟合，属正常保护逻辑，不影响指标。
