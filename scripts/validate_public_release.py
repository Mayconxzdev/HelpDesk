from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", "instance", "dist", "out", "build"}
SKIP_FILES = {".env.example", "package-lock.json", "validate_public_release.py"}
FORBIDDEN_NAMES = {".env", "helpdesk.db", "conversation_log.txt", "embeddings.pkl"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pkl", ".exe", ".zip", ".tar"}
TEXT_SUFFIXES = {
    ".py", ".js", ".json", ".md", ".html", ".css", ".yml", ".yaml",
    ".toml", ".txt", ".example", ".gitignore",
}
PATTERNS = {
    "hardcoded private IPv4": re.compile(r"(?<![\d.])(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?![\d.])"),
    "unsafe Electron nodeIntegration": re.compile(r"nodeIntegration\s*:\s*true", re.I),
    "unsafe Electron contextIsolation": re.compile(r"contextIsolation\s*:\s*false", re.I),
    "insecure Chromium switch": re.compile(r"unsafely-treat-insecure-origin|allow-running-insecure-content", re.I),
    "unsafe pickle load": re.compile(r"pickle\.load\("),
    "known demo API key": re.compile(r"dc6zaTOxFJmzC|LIVD5S2S3S0C|AIzaSy[A-Za-z0-9_-]{20,}"),
    "hardcoded password assignment": re.compile(r"password\s*[:=]\s*[\"'][^\"']{6,}[\"']", re.I),
}


def iter_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def main() -> int:
    failures = []
    for path in iter_files():
        rel = path.relative_to(ROOT)
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden artifact: {rel}")
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".gitignore"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{label}: {rel}")
    if failures:
        print("Public-release validation failed:")
        for failure in sorted(set(failures)):
            print(f"- {failure}")
        return 1
    print("Public-release validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
