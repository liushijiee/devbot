"""
DevBot 配置管理
所有敏感信息通过环境变量注入，不硬编码。
面试点：12-Factor App 配置外置原则。

校验策略（对齐 openreview lib/env.ts 的 fail-fast 思路）：
- 类型 / 取值范围校验在 Settings 构造时即生效（pydantic field_validator），
  默认值是合法的，所以 eval / 本地调用不会因此崩溃。
- GitLab 凭证缺失的「启动即失败」用 assert_gitlab_ready() 显式触发，
  只在 Webhook 入口（GitLabAdapter 初始化）调用，
  避免污染不需要 GitLab 的评测链路（eval 也会调 get_settings()）。
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings

_REQUIRED_GITLAB = ("gitlab_token", "gitlab_webhook_secret")


class Settings(BaseSettings):
    gitlab_token: str = ""
    gitlab_webhook_secret: str = ""
    gitlab_base_url: str = "https://gitlab.com"

    dashscope_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    critic_model: str = "glm-5.1"
    judge_model: str = "qwen3.7-plus"

    max_tool_rounds: int = 5
    max_file_lines_per_bundle: int = 800
    confidence_threshold: float = 0.4
    reflect_skip_confidence: float = 0.9
    risk_block_threshold: int = 70

    repo_clone_dir: str = "/tmp/devbot_repos"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("confidence_threshold", "reflect_skip_confidence")
    @classmethod
    def _check_confidence_range(cls, v: float) -> float:
        if not (0.0 < v <= 1.0):
            raise ValueError(f"置信度必须 ∈ (0, 1]，收到 {v}")
        return v

    @field_validator("max_tool_rounds", "max_file_lines_per_bundle", "risk_block_threshold")
    @classmethod
    def _check_positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"该参数必须为正整数，收到 {v}")
        return v

    def assert_gitlab_ready(self) -> None:
        """
        Webhook 启动 fail-fast：缺少任一必需 GitLab 凭证立即抛错。
        仅在 GitLabAdapter.__init__ 调用，eval 链路不受影响。
        """
        missing = [name for name in _REQUIRED_GITLAB if not getattr(self, name)]
        if missing:
            env_names = ", ".join(name.upper() for name in missing)
            raise RuntimeError(
                f"缺少必需的 GitLab 环境变量 (fail-fast): {env_names}。"
                f"请在 .env 中配置后再启动 DevBot Webhook 服务。"
            )


@lru_cache
def get_settings() -> Settings:
    """单例配置，全局复用。构造本身不 fail-fast（保留 eval 可用性）。"""
    return Settings()

