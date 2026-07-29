
from app.harness.diff_parser import FileChange

LANGUAGE_RULES: dict[str, list[str]] = {
    "python": [
        "检查是否缺少类型注解（函数参数和返回值）",
        "检查异常处理：是否有裸 except、是否吞掉了异常",
        "检查资源管理：文件/连接是否使用 with 语句",
        "检查可变默认参数（如 def f(items=[])）",
    ],
    "javascript": [
        "检查未处理的 Promise rejection",
        "检查 var 声明（应使用 let/const）",
        "检查 == 比较（应使用 ===）",
        "检查 XSS：用户输入是否经过转义后再渲染",
    ],
    "typescript": [
        "检查 any 类型滥用",
        "检查未处理的 Promise rejection",
        "检查类型断言（as）是否可以用类型守卫替代",
        "检查 XSS：用户输入是否经过转义",
    ],
    "java": [
        "检查空指针风险：方法返回值是否可能为 null",
        "检查线程安全：共享变量是否加锁",
        "检查资源泄漏：Stream/Connection 是否在 finally 中关闭",
        "检查 SQL 注入：是否使用参数化查询",
    ],
    "go": [
        "检查 error 是否被忽略（_ = someFunc()）",
        "检查 goroutine 泄漏：是否有未关闭的 channel",
        "检查并发安全：共享 map 是否加锁",
        "检查 defer 在循环中的使用",
    ],
    "sql": [
        "检查 SQL 注入风险：是否使用参数绑定",
        "检查是否有全表扫描（缺少 WHERE 或索引）",
        "检查 DDL 变更是否向后兼容",
    ],
}

PATH_RULES: list[dict] = [
    {
        "pattern": r".*/api/.*|.*route.*|.*controller.*",
        "rules": ["检查接口参数校验是否完整", "检查鉴权中间件是否生效"],
    },
    {
        "pattern": r".*/model.*|.*schema.*|.*entity.*",
        "rules": ["检查字段变更是否向后兼容", "检查数据库索引是否需要更新"],
    },
    {
        "pattern": r".*test.*|.*spec.*",
        "rules": ["检查测试覆盖是否充分", "检查 mock 是否合理"],
    },
    {
        "pattern": r".*/config.*|.*setting.*|.*\.env.*",
        "rules": ["检查是否有敏感信息硬编码", "检查配置项是否有默认值"],
    },
]

def match_rules(files: list[FileChange]) -> str:
    """
    主入口：根据文件列表的语言和路径，返回匹配到的规则文本。
    输出直接拼接到 Critic 的 system prompt 中。
    """
    import re

    matched_rules: set[str] = set()

    languages = {f.language for f in files}
    for lang in languages:
        if lang in LANGUAGE_RULES:
            matched_rules.update(LANGUAGE_RULES[lang])

    for file in files:
        for path_rule in PATH_RULES:
            if re.match(path_rule["pattern"], file.path, re.IGNORECASE):
                matched_rules.update(path_rule["rules"])

    if not matched_rules:
        return ""

    rules_text = "\n".join(f"  - {rule}" for rule in sorted(matched_rules))
    return f"\n【本次审查需重点关注的规则】\n{rules_text}\n"
