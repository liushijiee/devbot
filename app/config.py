"""
DevBot 配置管理
所有敏感信息通过环境变量注入，不硬编码。
面试点：12-Factor App 配置外置原则。
"""

from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):

    gitlab_token: str = ""
    gitlab_webhook_secret: str = ""
    gitlab_base_url: str = "https://gitlab.com"

    dashscope_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    critic_model: str = "qwen-max"
    judge_model: str = "qwen3.7-plus"

    max_tool_rounds: int = 12
    max_file_lines_per_bundle: int = 800
    confidence_threshold: float = 0.4
    risk_block_threshold: int = 70

    repo_clone_dir: str = "/tmp/devbot_repos"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

@lru_cache
def get_settings() -> Settings:
    """单例配置，全局复用。"""
    return Settings()

