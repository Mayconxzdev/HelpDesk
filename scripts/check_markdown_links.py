from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    missing = []
    for doc in ROOT.rglob("*.md"):
        if any(part in {".git", "node_modules", ".venv"} for part in doc.parts):
            continue
        text = doc.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            target = target.strip().split()[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = unquote(target.split("#", 1)[0])
            if not clean:
                continue
            resolved = (doc.parent / clean).resolve()
            if not resolved.exists():
                missing.append(f"{doc.relative_to(ROOT)} -> {target}")
    if missing:
        print("Broken local Markdown links:")
        for item in missing:
            print(f"- {item}")
        return 1
    print("Markdown links passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
