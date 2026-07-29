from pathlib import Path
from dataclasses import dataclass

import yaml

PROMPTS_DIR = Path(__file__).parent

@dataclass
class PromptTemplate:
    """一对 system + user prompt 模板。"""
    system: str
    user: str

    def format_user(self, **kwargs) -> str:
        """
        填充 user prompt 中的模板变量。
        使用 str.replace 而非 str.format，避免与 JSON 示例中的 {} 冲突。
        """
        result = self.user
        for key, value in kwargs.items():
            result = result.replace("{" + key + "}", str(value))
        return result

    def format_system(self, **kwargs) -> str:
        """填充 system prompt 中的模板变量（通常无变量，预留扩展）。"""
        result = self.system
        for key, value in kwargs.items():
            result = result.replace("{" + key + "}", str(value))
        return result

_cache: dict[str, PromptTemplate] = {}

def load_prompt(name: str) -> PromptTemplate:
    """
    按名字加载 prompt 模板。

    参数:
        name: 模板名（不含 .yaml 后缀），如 "correctness"、"reflector"

    返回:
        PromptTemplate(system=..., user=...)

    可用模板:
        - correctness: 逻辑正确性 Critic
        - security: 安全性 Critic
        - performance: 性能 Critic
        - quality: 工程质量 Critic
        - reflector: 后置验证 Reflector
    """
    if name in _cache:
        return _cache[name]

    file_path = PROMPTS_DIR / f"{name}.yaml"
    if not file_path.exists():
        available = [f.stem for f in PROMPTS_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"Prompt 模板 '{name}' 不存在。可用模板: {available}"
        )

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    template = PromptTemplate(
        system=data["system"],
        user=data["user"],
    )
    _cache[name] = template
    return template

def list_prompts() -> list[str]:
    """列出所有可用的 prompt 模板名。"""
    return sorted(f.stem for f in PROMPTS_DIR.glob("*.yaml"))

CRITIC_NAMES = ["correctness", "security", "performance", "quality"]
REFLECTOR_NAME = "reflector"
