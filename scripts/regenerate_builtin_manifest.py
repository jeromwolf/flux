#!/usr/bin/env python3
"""Regenerate ``src/flux/tools/builtins/_manifest.json``.

The manifest is a SHA-256 lockfile for builtin tools shipped with Flux.
ToolManager refuses to load a builtin whose hash doesn't match an entry in
this file — that's how we keep external PRs from sneaking past the AST scanner
by dropping a malicious tool into ``builtins/``.

Run this script every time you add, modify, or rename a builtin tool, then
commit the updated ``_manifest.json`` alongside the code change.

Usage::

    python scripts/regenerate_builtin_manifest.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BUILTINS_DIR = REPO_ROOT / "src" / "flux" / "tools" / "builtins"
MANIFEST_PATH = BUILTINS_DIR / "_manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not BUILTINS_DIR.is_dir():
        print(f"error: builtins dir not found at {BUILTINS_DIR}")
        return 1

    hashes: dict[str, str] = {}
    for entry in sorted(BUILTINS_DIR.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.endswith(".py"):
            continue
        if entry.name.startswith("_"):
            continue  # __init__.py and friends are not tools
        hashes[entry.name] = _sha256(entry)

    previous: dict[str, str] = {}
    if MANIFEST_PATH.exists():
        try:
            previous = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}

    MANIFEST_PATH.write_text(
        json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    added = sorted(set(hashes) - set(previous))
    removed = sorted(set(previous) - set(hashes))
    changed = sorted(
        name for name in set(hashes) & set(previous) if hashes[name] != previous[name]
    )
    unchanged = sorted(
        name for name in set(hashes) & set(previous) if hashes[name] == previous[name]
    )

    print(f"wrote {MANIFEST_PATH.relative_to(REPO_ROOT)} ({len(hashes)} tools)")
    if added:
        print("  added:    " + ", ".join(added))
    if changed:
        print("  changed:  " + ", ".join(changed))
    if removed:
        print("  removed:  " + ", ".join(removed))
    if not (added or changed or removed):
        print(f"  no changes ({len(unchanged)} tools unchanged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
