"""
Prompt Registry 测试
验证 YAML 模板加载和变量填充。
"""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.prompts.registry import load_prompt, list_prompts, CRITIC_NAMES, REFLECTOR_NAME

def test_list_prompts():
    print("=" * 50)
    print("TEST: list_prompts")
    print("=" * 50)
    prompts = list_prompts()
    print(f"可用模板: {prompts}")
    assert "correctness" in prompts
    assert "security" in prompts
    assert "performance" in prompts
    assert "quality" in prompts
    assert "reflector" in prompts
    print("[PASS] 所有模板存在\n")

def test_load_critic_prompt():
    print("=" * 50)
    print("TEST: load critic prompt")
    print("=" * 50)
    for name in CRITIC_NAMES:
        tpl = load_prompt(name)
        assert tpl.system, f"{name} system prompt 为空"
        assert tpl.user, f"{name} user prompt 为空"
        assert "{diff_text}" in tpl.user, f"{name} 缺少 diff_text 变量"
        assert "{rules}" in tpl.user, f"{name} 缺少 rules 变量"
        assert "{changed_files}" in tpl.user, f"{name} 缺少 changed_files 变量"
        print(f"  [{name}] system={len(tpl.system)}字符, user={len(tpl.user)}字符 ✓")
    print("[PASS] 4 个 Critic 模板加载正常\n")

def test_load_reflector_prompt():
    print("=" * 50)
    print("TEST: load reflector prompt")
    print("=" * 50)
    tpl = load_prompt(REFLECTOR_NAME)
    assert "{diff_text}" in tpl.user
    assert "{finding}" in tpl.user
    print(f"  [reflector] system={len(tpl.system)}字符, user={len(tpl.user)}字符 ✓")
    print("[PASS] Reflector 模板加载正常\n")

def test_format_user():
    print("=" * 50)
    print("TEST: format_user 变量填充")
    print("=" * 50)
    tpl = load_prompt("correctness")
    filled = tpl.format_user(
        changed_files="- src/auth/login.py\n- src/routes.py",
        diff_text="@@ -1,3 +1,5 @@\n+def new_func():\n+    pass",
        rules="- 检查异常处理",
    )
    assert "src/auth/login.py" in filled
    assert "new_func" in filled
    assert "检查异常处理" in filled
    assert "{diff_text}" not in filled
    print(f"  填充后 user prompt: {len(filled)} 字符")
    print(f"  前 200 字符: {filled[:200]}...")
    print("[PASS] 变量填充正确\n")

def test_format_reflector():
    print("=" * 50)
    print("TEST: reflector format_user")
    print("=" * 50)
    tpl = load_prompt("reflector")
    filled = tpl.format_user(
        diff_text="@@ -10,4 +10,6 @@\n+    if not user:\n+        raise AuthError()",
        finding='{"file": "src/login.py", "line": 11, "severity": "warning", "title": "test"}',
    )
    assert "AuthError" in filled
    assert "src/login.py" in filled
    print("[PASS] Reflector 变量填充正确\n")

def test_not_found():
    print("=" * 50)
    print("TEST: 不存在的模板")
    print("=" * 50)
    try:
        load_prompt("nonexistent")
        assert False, "应该抛出 FileNotFoundError"
    except FileNotFoundError as e:
        print(f"  错误信息: {e}")
        assert "nonexistent" in str(e)
    print("[PASS] 正确抛出异常\n")

if __name__ == "__main__":
    test_list_prompts()
    test_load_critic_prompt()
    test_load_reflector_prompt()
    test_format_user()
    test_format_reflector()
    test_not_found()

    print("=" * 50)
    print("ALL TESTS PASSED!")
    print("=" * 50)
