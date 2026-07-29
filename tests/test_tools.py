"""
工具层测试
模拟一个已 clone 的仓库，验证 3 个工具的正确性。
"""
import sys
import io
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.harness.diff_parser import FileChange, Hunk
from app.harness.repo_manager import RepoManager
from app.tools.code_tools import create_tools

def setup_fake_repo() -> tuple[RepoManager, list[FileChange]]:
    """创建一个模拟仓库 + 模拟 diff 数据。"""

    tmp = tempfile.mkdtemp()
    repo_path = Path(tmp)

    (repo_path / "src").mkdir(parents=True)
    (repo_path / "src" / "auth").mkdir()

    login_py = '''\
def login_handler(username, password):
    user = query_user(username.strip())
    if not user:
        raise AuthError("user not found")
    return generate_token(user)

def query_user(username):
    return db.query(User).filter_by(name=username).first()
'''
    (repo_path / "src" / "auth" / "login.py").write_text(login_py, encoding="utf-8")

    routes_py = '''\
from src.auth.login import login_handler

def handle_login(request):
    username = request.json["username"]
    password = request.json["password"]
    token = login_handler(username, password)
    return {"token": token}
'''
    (repo_path / "src" / "routes.py").write_text(routes_py, encoding="utf-8")

    rm = RepoManager()
    rm._clone_path = repo_path

    changes = [
        FileChange(
            path="src/auth/login.py",
            language="python",
            changed_lines=3,
            is_new=False,
            is_deleted=False,
            diff_text="@@ -1,3 +1,5 @@\n def login_handler(username, password):\n-    user = query_user(username)\n+    user = query_user(username.strip())\n+    if not user:\n+        raise AuthError(\"user not found\")\n     return generate_token(user)",
        ),
        FileChange(
            path="src/routes.py",
            language="python",
            changed_lines=1,
            is_new=False,
            is_deleted=False,
            diff_text="@@ -1,3 +1,4 @@\n from src.auth.login import login_handler\n+from src.auth.token import refresh_token",
        ),
    ]

    return rm, changes

def test_read_file(tools):
    print("=" * 50)
    print("TEST: read_file")
    print("=" * 50)

    result = tools[0].invoke({"path": "src/auth/login.py"})
    print(result)
    assert "login_handler" in result
    print("[PASS] 正常读取\n")

    result = tools[0].invoke({"path": "src/auth/login.py", "start_line": 1, "end_line": 3})
    print(result)
    assert "db.query" not in result
    print("[PASS] 行范围裁剪\n")

    result = tools[0].invoke({"path": "../../etc/passwd"})
    print(result)
    assert "越界" in result or "错误" in result
    print("[PASS] 路径逃逸拦截\n")

    result = tools[0].invoke({"path": "not_exist.py"})
    print(result)
    assert "不存在" in result
    print("[PASS] 文件不存在处理\n")

def test_grep(tools):
    print("=" * 50)
    print("TEST: grep")
    print("=" * 50)

    result = tools[1].invoke({"pattern": "login_handler"})
    print(result)
    assert "routes.py" in result
    assert "login.py" in result
    print("[PASS] 全仓库搜索\n")

    result = tools[1].invoke({"pattern": "login_handler", "path": "src/auth"})
    print(result)
    assert "routes.py" not in result
    print("[PASS] 限定目录搜索\n")

    result = tools[1].invoke({"pattern": "import", "file_glob": "*.py"})
    print(result)
    assert "import" in result
    print("[PASS] 文件类型过滤\n")

    result = tools[1].invoke({"pattern": "zzz_not_exist_zzz"})
    print(result)
    assert "未找到" in result
    print("[PASS] 无结果处理\n")

def test_get_diff_file(tools):
    print("=" * 50)
    print("TEST: get_diff_file")
    print("=" * 50)

    result = tools[2].invoke({"path": "src/auth/login.py"})
    print(result)
    assert "query_user" in result
    assert "strip" in result
    print("[PASS] 获取变更文件 diff\n")

    result = tools[2].invoke({"path": "src/config.py"})
    print(result)
    assert "不在本次 MR" in result
    assert "src/auth/login.py" in result
    print("[PASS] 非变更文件提示\n")

if __name__ == "__main__":
    print(">>> 初始化模拟仓库...")
    rm, changes = setup_fake_repo()
    tools = create_tools(rm, changes)
    print(f">>> 创建 {len(tools)} 个工具: {[t.name for t in tools]}\n")

    test_read_file(tools)
    test_grep(tools)
    test_get_diff_file(tools)

    print("=" * 50)
    print("ALL TESTS PASSED!")
    print("=" * 50)

    rm.cleanup()
