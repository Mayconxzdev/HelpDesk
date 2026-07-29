from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_JSON = ROOT / "hd_electron" / "package.json"
LOCK_FILE = ROOT / "hd_electron" / "package-lock.json"


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def satisfies(version: tuple[int, int, int], raw_spec: str) -> bool | None:
    spec = raw_spec.strip()
    if spec.startswith("npm:"):
        _, _, spec = spec.rpartition("@")
    spec = re.sub(r"([<>]=?|[~^=])\s+(?=\d)", r"\1", spec)

    if not spec or spec in {"*", "latest"}:
        return True
    if spec.startswith(("git+", "git://", "http://", "https://", "file:", "workspace:")):
        return None
    if "||" in spec:
        outcomes = [satisfies(version, item) for item in spec.split("||")]
        known = [outcome for outcome in outcomes if outcome is not None]
        return any(known) if known else None

    hyphen = re.match(r"^(\d+(?:\.\d+){0,2})\s+-\s+(\d+(?:\.\d+){0,2})$", spec)
    if hyphen:
        lower = parse_version(hyphen.group(1))
        upper = parse_version(hyphen.group(2))
        return bool(lower and upper and lower <= version <= upper)

    if " " in spec:
        outcomes = [satisfies(version, token) for token in spec.split()]
        known = [outcome for outcome in outcomes if outcome is not None]
        return all(known) if known else None

    operator = ""
    for candidate in (">=", "<=", ">", "<", "^", "~", "="):
        if spec.startswith(candidate):
            operator = candidate
            spec = spec[len(candidate):].strip()
            break

    if any(character in spec.lower() for character in ("x", "*")):
        for index, part in enumerate(spec.split(".")):
            if part.lower() in {"x", "*"}:
                break
            if not part.isdigit() or version[index] != int(part):
                return False
        return True

    requested = parse_version(spec)
    if requested is None:
        return None
    if operator in {"", "="}:
        parts = spec.split(".")
        if len(parts) == 1:
            return version[0] == requested[0]
        if len(parts) == 2:
            return version[:2] == requested[:2]
        return version == requested
    if operator == ">=":
        return version >= requested
    if operator == "<=":
        return version <= requested
    if operator == ">":
        return version > requested
    if operator == "<":
        return version < requested
    if operator == "~":
        return requested <= version < (requested[0], requested[1] + 1, 0)
    if operator == "^":
        if requested[0] > 0:
            upper = (requested[0] + 1, 0, 0)
        elif requested[1] > 0:
            upper = (0, requested[1] + 1, 0)
        else:
            upper = (0, 0, requested[2] + 1)
        return requested <= version < upper
    return None


def resolve_package(packages: dict[str, dict], package_path: str, name: str) -> str | None:
    current = package_path
    while True:
        candidate = f"{current}/node_modules/{name}".strip("/")
        if candidate in packages:
            return candidate
        if "/node_modules/" not in current:
            break
        current = current.rsplit("/node_modules/", 1)[0]
    candidate = f"node_modules/{name}"
    return candidate if candidate in packages else None


def main() -> int:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    root = packages.get("", {})
    overrides = package.get("overrides", {})
    failures: list[str] = []

    for field in ("name", "version"):
        if root.get(field) != package.get(field):
            failures.append(f"package-lock root {field} differs from package.json")
    if root.get("devDependencies", {}) != package.get("devDependencies", {}):
        failures.append("package-lock root devDependencies differ from package.json")

    checked = 0
    unsupported: list[str] = []
    for package_path, metadata in packages.items():
        if not package_path:
            continue
        for field in ("dependencies", "optionalDependencies"):
            for name, spec in metadata.get(field, {}).items():
                resolved_path = resolve_package(packages, package_path, name)
                if not resolved_path:
                    if field != "optionalDependencies":
                        failures.append(f"missing locked dependency: {package_path} -> {name} ({spec})")
                    continue
                installed = str(packages[resolved_path].get("version", ""))
                parsed = parse_version(installed)
                if parsed is None:
                    unsupported.append(f"{package_path} -> {name} ({spec})")
                    continue
                override = overrides.get(name)
                effective_spec = str(override) if isinstance(override, str) else str(spec)
                outcome = satisfies(parsed, effective_spec)
                checked += 1
                if outcome is False:
                    failures.append(
                        f"incompatible lock: {package_path} requires {name} {effective_spec}, locked {installed}"
                    )
                elif outcome is None:
                    unsupported.append(f"{package_path} -> {name} ({spec})")

    if failures:
        print("npm lock validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"npm lock validation passed ({checked} dependency constraints checked).")
    if unsupported:
        print(f"Skipped {len(unsupported)} non-semver dependency specifications.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
