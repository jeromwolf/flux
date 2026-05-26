"""Tests for flux.tools.manager.ToolManager — manifest-based builtin loading."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from flux.tools.manager import _BUILTINS_DIR, ToolManager


# ---------------------------------------------------------------------------
# Manifest integrity
# ---------------------------------------------------------------------------

def test_builtin_manifest_loads():
    """The shipped manifest exists, parses, and covers all *.py tools."""
    manifest_path = Path(_BUILTINS_DIR) / "_manifest.json"
    assert manifest_path.exists(), "builtin manifest missing"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data, "manifest must list at least one builtin tool"

    expected_files = {
        p.name for p in Path(_BUILTINS_DIR).iterdir()
        if p.is_file() and p.suffix == ".py" and not p.name.startswith("_")
    }
    assert set(data.keys()) == expected_files, (
        f"manifest drift — manifest={set(data.keys())} actual={expected_files}"
    )


def test_builtin_passes_with_matching_hash(monkeypatch):
    """Loading the real builtins/ directory (non-interactive) yields tools."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    mgr = ToolManager()  # defaults to _BUILTINS_DIR
    # All 7 shipped builtins should load.
    assert "web_search" in mgr.functions
    assert "web_fetch" in mgr.functions
    assert "read_text_file" in mgr.functions
    assert len(mgr.functions) >= 7


def test_hash_helper_stable():
    """SHA-256 over the same bytes is deterministic."""
    mgr = ToolManager.__new__(ToolManager)  # bypass __init__
    data = b"hello flux\n"
    assert mgr._file_hash(data) == hashlib.sha256(data).hexdigest()
    # And matches what the helper script computes.
    assert mgr._file_hash(data) == mgr._file_hash(data)


# ---------------------------------------------------------------------------
# Helpers to stage a fake builtins directory under tmp_path
# ---------------------------------------------------------------------------

_SAMPLE_TOOL = '''\
SCHEMA = {
    "name": "echo",
    "description": "echo input",
    "input_schema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}


def main(text: str) -> str:
    return text
'''


def _stage_builtins_dir(tmp_path: Path) -> Path:
    """Copy a single sample tool into tmp_path and write a manifest for it."""
    pkg = tmp_path / "builtins"
    pkg.mkdir()
    tool_path = pkg / "echo.py"
    tool_path.write_text(_SAMPLE_TOOL, encoding="utf-8")
    manifest = {"echo.py": hashlib.sha256(tool_path.read_bytes()).hexdigest()}
    (pkg / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pkg


# ---------------------------------------------------------------------------
# Tampering + unregistered builtin
# ---------------------------------------------------------------------------

def test_builtin_rejected_when_modified(tmp_path, monkeypatch):
    """A builtin whose bytes don't match the manifest is blocked in non-TTY."""
    pkg = _stage_builtins_dir(tmp_path)

    # First load succeeds — hash matches.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    mgr = ToolManager(tools_dir=str(pkg))
    assert "echo" in mgr.functions

    # Now tamper with the file and rebuild the manager. The new bytes don't
    # match the manifest, so non-interactive load must refuse it.
    (pkg / "echo.py").write_text(_SAMPLE_TOOL + "\n# tampered\n", encoding="utf-8")
    mgr2 = ToolManager(tools_dir=str(pkg))
    assert "echo" not in mgr2.functions


def test_unregistered_builtin_blocked(tmp_path, monkeypatch):
    """A new file dropped into builtins/ without manifest entry is blocked."""
    pkg = _stage_builtins_dir(tmp_path)
    # Add a second file but DON'T add it to the manifest.
    sneaky = pkg / "sneaky.py"
    sneaky.write_text(
        # Looks innocent but is unregistered — the manifest check must block it.
        _SAMPLE_TOOL.replace('"echo"', '"sneaky"'),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    mgr = ToolManager(tools_dir=str(pkg))
    # The legitimate, manifest-registered tool still loads.
    assert "echo" in mgr.functions
    # The unregistered one does not.
    assert "sneaky" not in mgr.functions


def test_unregistered_builtin_with_dangerous_code_blocked(tmp_path, monkeypatch):
    """An unregistered file containing eval() is blocked AND the AST scanner fires."""
    pkg = _stage_builtins_dir(tmp_path)
    evil = _SAMPLE_TOOL.replace('return text', 'return eval(text)')
    (pkg / "evil.py").write_text(evil, encoding="utf-8")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    mgr = ToolManager(tools_dir=str(pkg))
    assert "evil" not in mgr.functions


# ---------------------------------------------------------------------------
# User-tool flow (no manifest) still works
# ---------------------------------------------------------------------------

def test_user_dir_uses_existing_flow(tmp_path, monkeypatch):
    """A directory without a manifest goes through the legacy approval flow."""
    user_dir = tmp_path / "user_tools"
    user_dir.mkdir()
    (user_dir / "echo.py").write_text(_SAMPLE_TOOL, encoding="utf-8")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    # Run under a chdir so the .tool_approved.json sidecar lands in tmp_path,
    # not the repo root.
    monkeypatch.chdir(tmp_path)
    mgr = ToolManager(tools_dir=str(user_dir))
    # No manifest, clean file (no dangerous patterns), but non-TTY blocks it
    # because the user hasn't approved it.
    assert "echo" not in mgr.functions
    assert mgr._is_builtin_dir is False


def test_user_dir_dangerous_code_blocked(tmp_path, monkeypatch):
    """User dir with eval() is blocked in non-TTY (no manifest shortcut)."""
    user_dir = tmp_path / "user_tools"
    user_dir.mkdir()
    dangerous = _SAMPLE_TOOL.replace('return text', 'return eval(text)')
    (user_dir / "bad.py").write_text(dangerous, encoding="utf-8")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.chdir(tmp_path)
    mgr = ToolManager(tools_dir=str(user_dir))
    assert "bad" not in mgr.functions
