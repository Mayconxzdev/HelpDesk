from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_rendered_templates_exist():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    referenced = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "render_template":
            if node.args and isinstance(node.args[0], ast.Constant):
                referenced.add(node.args[0].value)
    missing = [name for name in referenced if not (ROOT / "templates" / name).exists()]
    assert missing == []


def test_no_public_runtime_database_is_committed():
    forbidden_suffixes = {".db", ".sqlite", ".sqlite3", ".pkl"}
    committed = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]
    assert committed == []
