"""
Platt 校准器
修正 LLM 的 confidence 过度自信问题。

原理：
  LLM 说 confidence=0.9，但实际正确率可能只有 0.6。
  Platt Scaling 用一条 sigmoid 曲线拟合 (原始confidence → 真实正确率) 的映射。
  本质就是对 confidence 做 Logistic Regression。

数据来源：
  harness.run_eval_suite() 返回的 calibration_data，
  即 [(confidence, is_correct), ...] —— confidence 是 Critic 的原始输出，
  is_correct 是与 ground truth 匹配的客观结果。
"""

import json
import logging
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

logger = logging.getLogger(__name__)


class PlattCalibrator:
    """
    Platt Scaling 校准器。

    训练数据：[(confidence, is_correct), ...]
    训练后：calibrate(0.9) → 0.65（校准后的真实概率）
    """

    def __init__(self):
        self._model: LogisticRegression | None = None
        self._is_fitted = False

    def fit(self, calibration_data: list[dict]):
        """
        训练校准器。

        参数:
            calibration_data: [{"confidence": 0.8, "is_correct": True}, ...]
                             至少需要 5 条数据才能有效拟合。
        """
        if len(calibration_data) < 5:
            logger.warning(f"校准数据不足（{len(calibration_data)} 条），至少需要 5 条")
            return

        X = np.array([[d["confidence"]] for d in calibration_data])
        y = np.array([1 if d["is_correct"] else 0 for d in calibration_data])

        if len(set(y)) < 2:
            logger.warning("校准数据中全部为同一类别（全对或全错），无法校准")
            return

        # Platt Scaling = sigmoid(confidence * w + b)
        self._model = LogisticRegression(C=1e10, solver="lbfgs", max_iter=1000)
        self._model.fit(X, y)

        self._is_fitted = True
        logger.info(f"Platt 校准器训练完成（{len(calibration_data)} 条数据）")

    def calibrate(self, confidence: float) -> float:
        """
        校准单个 confidence 值。

        参数:
            confidence: 原始 confidence（0-1）
        返回:
            校准后的概率（0-1）
        """
        if not self._is_fitted:
            return confidence

        X = np.array([[confidence]])
        proba = self._model.predict_proba(X)[0][1]
        return round(float(proba), 4)

    def calibrate_comments(self, comments: list[dict]) -> list[dict]:
        """批量校准评论中的 confidence（从 body 中提取的置信度仅作参考展示）。"""
        from app.eval.harness import extract_confidence

        calibrated = []
        for c in comments:
            c_copy = dict(c)
            raw = extract_confidence(c.get("body", ""))
            c_copy["raw_confidence"] = raw
            c_copy["calibrated_confidence"] = self.calibrate(raw)
            calibrated.append(c_copy)
        return calibrated

    def save(self, path: str | Path):
        """保存校准器参数到 JSON。"""
        if not self._is_fitted:
            logger.warning("校准器未训练，无法保存")
            return

        params = {
            "coef": self._model.coef_.tolist(),
            "intercept": self._model.intercept_.tolist(),
        }
        Path(path).write_text(json.dumps(params), encoding="utf-8")
        logger.info(f"校准器已保存: {path}")

    def load(self, path: str | Path):
        """从 JSON 加载校准器参数。"""
        path = Path(path)
        if not path.exists():
            logger.warning(f"校准器文件不存在: {path}")
            return

        params = json.loads(path.read_text(encoding="utf-8"))

        self._model = LogisticRegression(C=1e10, solver="lbfgs")
        self._model.coef_ = np.array(params["coef"])
        self._model.intercept_ = np.array(params["intercept"])
        self._model.classes_ = np.array([0, 1])

        self._is_fitted = True
        logger.info(f"校准器已加载: {path}")

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted
