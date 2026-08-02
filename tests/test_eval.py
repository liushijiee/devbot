"""
Eval 模块测试
验证：指标计算、匹配逻辑、Platt 校准器。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.eval.metrics import MatchResult, compute_metrics
from app.eval.harness import (
    load_dataset,
    match_findings_to_truth,
    run_eval_case,
    run_eval_suite,
    EvalCase,
)
from app.eval.calibrator import PlattCalibrator


# ── 指标计算测试 ──

def test_compute_metrics_perfect():
    """全部命中：precision=1, recall=1, f1=1"""
    matches = [
        MatchResult(finding={"file": "a.py", "line": 1}, is_correct=True, confidence=0.9),
        MatchResult(finding={"file": "b.py", "line": 2}, is_correct=True, confidence=0.8),
    ]
    m = compute_metrics(matches, total_ground_truth=2)
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0


def test_compute_metrics_partial():
    """2 个 findings，1 个正确，ground truth 共 2 个 → P=0.5, R=0.5"""
    matches = [
        MatchResult(finding={"file": "a.py", "line": 1}, is_correct=True, confidence=0.9),
        MatchResult(finding={"file": "c.py", "line": 9}, is_correct=False, confidence=0.7),
    ]
    m = compute_metrics(matches, total_ground_truth=2)
    assert m["precision"] == 0.5
    assert m["recall"] == 0.5


def test_compute_metrics_empty():
    """无 findings → precision=0"""
    m = compute_metrics([], total_ground_truth=3)
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0
    assert m["f1"] == 0.0


# ── 匹配逻辑测试 ──

def test_match_exact():
    """精确匹配：同文件同行号"""
    findings = [{"file": "src/login.py", "line": 12, "confidence": 0.85}]
    gt = [{"file": "src/login.py", "line": 12, "severity": "warning"}]
    results = match_findings_to_truth(findings, gt)
    assert results[0].is_correct is True


def test_match_tolerance():
    """行号容差：差 2 行仍匹配"""
    findings = [{"file": "src/login.py", "line": 14, "confidence": 0.8}]
    gt = [{"file": "src/login.py", "line": 12, "severity": "warning"}]
    results = match_findings_to_truth(findings, gt, line_tolerance=3)
    assert results[0].is_correct is True


def test_match_no_match():
    """不同文件 → 不匹配"""
    findings = [{"file": "src/other.py", "line": 12, "confidence": 0.9}]
    gt = [{"file": "src/login.py", "line": 12, "severity": "warning"}]
    results = match_findings_to_truth(findings, gt)
    assert results[0].is_correct is False


def test_match_fuzzy_path():
    """路径尾部匹配：src/login.py vs login.py"""
    findings = [{"file": "src/login.py", "line": 12, "confidence": 0.85}]
    gt = [{"file": "login.py", "line": 12, "severity": "warning"}]
    results = match_findings_to_truth(findings, gt)
    assert results[0].is_correct is True


# ── 数据集加载测试 ──

def test_load_dataset():
    """加载示例数据集"""
    dataset_path = Path(__file__).resolve().parent.parent / "app" / "eval" / "sample_dataset.json"
    cases = load_dataset(dataset_path)
    assert len(cases) == 3
    assert cases[0].case_id == "case_001"
    assert len(cases[2].ground_truth) == 2


# ── 评测套件测试 ──

def test_run_eval_suite():
    """模拟完整评测流程"""
    cases = [
        EvalCase(case_id="c1", diff_text="...", language="python",
                 ground_truth=[{"file": "a.py", "line": 5, "severity": "warning"}]),
        EvalCase(case_id="c2", diff_text="...", language="python",
                 ground_truth=[{"file": "b.py", "line": 10, "severity": "critical"}]),
    ]
    findings_per_case = {
        "c1": [{"file": "a.py", "line": 5, "confidence": 0.9}],
        "c2": [{"file": "b.py", "line": 20, "confidence": 0.7}],
    }
    result = run_eval_suite(cases, findings_per_case)

    assert result["total_cases"] == 2
    assert result["total_findings"] == 2
    assert result["metrics"]["precision"] == 0.5
    assert result["metrics"]["recall"] == 0.5
    assert len(result["calibration_data"]) == 2


# ── Platt 校准器测试 ──

def test_calibrator_fit_and_calibrate():
    """训练 + 校准基本功能"""
    data = [
        {"confidence": 0.9, "is_correct": True},
        {"confidence": 0.9, "is_correct": False},
        {"confidence": 0.85, "is_correct": True},
        {"confidence": 0.85, "is_correct": False},
        {"confidence": 0.8, "is_correct": True},
        {"confidence": 0.8, "is_correct": False},
        {"confidence": 0.7, "is_correct": True},
        {"confidence": 0.6, "is_correct": True},
        {"confidence": 0.5, "is_correct": False},
        {"confidence": 0.4, "is_correct": False},
        {"confidence": 0.3, "is_correct": False},
        {"confidence": 0.2, "is_correct": False},
    ]

    cal = PlattCalibrator()
    assert cal.is_fitted is False

    cal.fit(data)
    assert cal.is_fitted is True

    calibrated_09 = cal.calibrate(0.9)
    calibrated_02 = cal.calibrate(0.2)

    assert calibrated_09 > calibrated_02
    assert 0 <= calibrated_09 <= 1
    assert 0 <= calibrated_02 <= 1

    print(f"  原始 0.9 → 校准后 {calibrated_09}")
    print(f"  原始 0.2 → 校准后 {calibrated_02}")


def test_calibrator_unfitted():
    """未训练时原样返回"""
    cal = PlattCalibrator()
    assert cal.calibrate(0.85) == 0.85


def test_calibrator_batch():
    """批量校准 findings"""
    data = [
        {"confidence": 0.9, "is_correct": True},
        {"confidence": 0.9, "is_correct": False},
        {"confidence": 0.5, "is_correct": True},
        {"confidence": 0.5, "is_correct": False},
        {"confidence": 0.3, "is_correct": False},
        {"confidence": 0.7, "is_correct": True},
    ]
    cal = PlattCalibrator()
    cal.fit(data)

    findings = [
        {"file": "a.py", "line": 1, "confidence": 0.9},
        {"file": "b.py", "line": 2, "confidence": 0.3},
    ]
    calibrated = cal.calibrate_findings(findings)

    assert "raw_confidence" in calibrated[0]
    assert calibrated[0]["raw_confidence"] == 0.9
    assert calibrated[0]["confidence"] != 0.9


# ── 运行所有测试 ──

if __name__ == "__main__":
    tests = [
        test_compute_metrics_perfect,
        test_compute_metrics_partial,
        test_compute_metrics_empty,
        test_match_exact,
        test_match_tolerance,
        test_match_no_match,
        test_match_fuzzy_path,
        test_load_dataset,
        test_run_eval_suite,
        test_calibrator_fit_and_calibrate,
        test_calibrator_unfitted,
        test_calibrator_batch,
    ]

    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__} → {e}")

    print(f"\n{'='*40}")
    print(f"结果: {passed}/{len(tests)} 通过")
