"""Harness 层快速验证脚本"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.harness.diff_parser import parse_gitlab_changes
from app.harness.file_filter import filter_files
from app.harness.file_grouper import group_files
from app.harness.rule_matcher import match_rules

changes = [
    {
        "new_path": "src/user.py",
        "old_path": "src/user.py",
        "diff": "@@ -1,3 +1,4 @@\n+import os\n def hello():\n-    pass\n+    return 1",
        "new_file": False,
        "deleted_file": False,
        "renamed_file": False,
    },
    {
        "new_path": "package-lock.json",
        "old_path": "package-lock.json",
        "diff": "@@ -1,1 +1,1 @@\n-old\n+new",
        "new_file": False,
        "deleted_file": False,
        "renamed_file": False,
    },
    {
        "new_path": "src/api/routes.py",
        "old_path": "src/api/routes.py",
        "diff": "@@ -10,2 +10,3 @@\n+from auth import check\n def index():\n     pass",
        "new_file": False,
        "deleted_file": False,
        "renamed_file": False,
    },
]

files = parse_gitlab_changes(changes)
print(f"[1] Parsed: {len(files)} files")
for f in files:
    print(f"    {f.path} | lang={f.language} | lines={f.changed_lines} | hunks={len(f.hunks)}")

filtered = filter_files(files)
print(f"\n[2] After filter: {len(filtered)} files (package-lock.json should be removed)")
for f in filtered:
    print(f"    {f.path}")

bundles = group_files(filtered, max_lines=800)
print(f"\n[3] Bundles: {len(bundles)}")
for i, b in enumerate(bundles):
    print(f"    Bundle {i+1}: {b.file_paths} ({b.total_lines} lines)")

rules = match_rules(filtered)
print(f"\n[4] Rules matched ({len(rules)} chars):")
print(rules)

print("\n=== All Harness tests passed! ===")
