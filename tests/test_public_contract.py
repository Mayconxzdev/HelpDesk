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


def test_no_public_runtime_artifacts_are_committed():
    forbidden_suffixes = {".db", ".sqlite", ".sqlite3", ".pkl", ".pyc", ".pyo"}
    forbidden_directories = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    committed_files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]
    committed_directories = [
        path
        for path in ROOT.rglob("*")
        if path.is_dir() and path.name in forbidden_directories
    ]
    assert committed_files == []
    assert committed_directories == []


def test_example_sqlite_url_does_not_duplicate_instance_directory():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DATABASE_URL=sqlite:///helpdesk.db" in example
    assert "sqlite:///instance/" not in example


def test_ci_uses_test_owned_database_configuration():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "DATABASE_URL:" not in workflow
    assert "python -m pytest -q" in workflow
