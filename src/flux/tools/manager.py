"""
flux.tools.manager - ToolManager for automatic tool loading, hot-reload, and security scanning.

Unified from openclaw tool_manager.py, tool_input.py, and tool_executor.py.
"""

from __future__ import annotations

import os
import sys
import json
import ast
import hashlib
import types
from pathlib import Path

from flux.safety.scanner import _DANGEROUS_RE

# Logging setup
try:
    from flux.logging import get_logger
    logger = get_logger("tools.manager")
except ImportError:
    import logging
    logger = logging.getLogger("tools.manager")

# Default builtins directory relative to this file
_BUILTINS_DIR = str(Path(__file__).parent / "builtins")


# ============================================================
# Tool Input Filtering
# ============================================================

_TYPE_MAP = {"string": str, "integer": int, "number": (int, float), "boolean": bool}


def _filter_tool_input(tool_input, schema):
    """Filter tool input to only schema-defined keys + type validation."""
    properties = schema.get("input_schema", {}).get("properties", {})
    if not properties:
        return tool_input
    filtered = {}
    for k, v in tool_input.items():
        if k not in properties:
            continue
        expected_type = properties[k].get("type")
        if expected_type and expected_type in _TYPE_MAP:
            if not isinstance(v, _TYPE_MAP[expected_type]):
                continue  # Type mismatch -> skip
        filtered[k] = v
    return filtered


# ============================================================
# ToolManager
# ============================================================

class ToolManager:
    """Watches a tools directory and auto-reloads on file add/modify/delete.

    By default loads from src/flux/tools/builtins/. Pass a custom tools_dir
    to load from a different location (e.g. a user-configured directory).

    Security model for builtins
    ---------------------------
    Earlier versions of this class auto-approved *any* file dropped into the
    builtins directory, which meant an attacker who could ship code through a
    PR could bypass the AST scanner entirely. We now require a SHA-256
    manifest (``_manifest.json``) co-located with the tools; a builtin loads
    without prompting only if its hash matches the manifest entry. Any
    mismatch, missing entry, or absent manifest forces the standard scan +
    approval flow.
    """

    _APPROVED_FILE = ".tool_approved.json"
    _MANIFEST_FILE = "_manifest.json"

    def __init__(self, tools_dir: str | None = None):
        self.tools_dir = tools_dir if tools_dir is not None else _BUILTINS_DIR
        # A directory is treated as "builtin-like" iff it ships a manifest.
        # This lets tests stage a fake builtins dir under tmp_path simply by
        # writing a manifest there.
        self._manifest_path = os.path.join(self.tools_dir, self._MANIFEST_FILE)
        self._is_builtin_dir = os.path.isfile(self._manifest_path)
        self._builtin_hashes: dict = self._load_builtin_manifest()
        self.schemas: list = []
        self.functions: dict = {}
        self._file_mtimes: dict = {}
        self._approved: set = set()  # User-approved files (in-session)
        self._load_all(first_load=True)

    def _load_builtin_manifest(self) -> dict:
        """Load the SHA-256 manifest for builtin tools.

        Returns an empty dict if the manifest doesn't exist or fails to parse —
        in that case the standard scan + approval flow takes over.
        """
        if not self._is_builtin_dir:
            return {}
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to load builtin manifest {self._manifest_path}: {e}")
            return {}
        if not isinstance(data, dict):
            logger.warning(f"Builtin manifest is not a JSON object: {self._manifest_path}")
            return {}
        return data

    # ----------------------------------------------------------
    # File scanning
    # ----------------------------------------------------------

    def _scan_files(self) -> dict:
        """Return {filename: mtime} for all .py files in tools_dir."""
        mtimes = {}
        if not os.path.isdir(self.tools_dir):
            return mtimes
        for fname in os.listdir(self.tools_dir):
            if fname.endswith(".py") and not fname.startswith("_"):
                path = os.path.join(self.tools_dir, fname)
                mtimes[fname] = os.path.getmtime(path)
        return mtimes

    # ----------------------------------------------------------
    # Security scanning
    # ----------------------------------------------------------

    def _check_dangerous(self, code: str) -> list:
        """Regex-based dangerous pattern detection. Returns found patterns."""
        return _DANGEROUS_RE.findall(code)

    def _check_dangerous_ast(self, code: str) -> list:
        """AST-based dangerous code detection (obfuscation bypass prevention)."""
        _BLOCKED_IMPORTS = {
            "subprocess", "ctypes", "pickle", "shutil", "base64", "codecs", "binascii",
            "webbrowser", "http", "multiprocessing", "threading", "signal", "atexit",
            "zipfile", "tarfile", "xml", "urllib", "tempfile", "sys",
            "glob", "pathlib", "requests", "httpx", "aiohttp", "urllib3",
            "pdb",
        }
        _BLOCKED_ATTRS = {"__builtins__", "__code__", "__class__", "__subclasses__", "__globals__"}
        _BLOCKED_CALLS = {
            "os.remove", "os.unlink", "os.rename", "os.chmod", "os.rmdir", "os.makedirs",
            "os.environ", "os.getenv", "os.listdir", "os.walk", "os.scandir",
        }
        _BLOCKED_BUILTINS = {
            "open", "exec", "eval", "compile", "getattr", "__import__",
            "type", "vars", "locals", "dir", "breakpoint", "memoryview",
        }
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ["SyntaxError"]
        findings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in _BLOCKED_IMPORTS:
                        findings.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in _BLOCKED_IMPORTS:
                    findings.append(f"from {node.module}")
            elif isinstance(node, ast.Attribute) and node.attr in _BLOCKED_ATTRS:
                findings.append(f"{node.attr}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    call_name = f"{node.func.value.id}.{node.func.attr}"
                    if call_name in _BLOCKED_CALLS:
                        findings.append(f"call {call_name}")
                elif isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_BUILTINS:
                    findings.append(f"builtin {node.func.id}")
        return findings

    # ----------------------------------------------------------
    # Hash-based approval persistence
    # ----------------------------------------------------------

    def _file_hash(self, raw_bytes: bytes) -> str:
        """Compute SHA-256 hash of file contents."""
        return hashlib.sha256(raw_bytes).hexdigest()

    def _load_approved_hashes(self) -> dict:
        """Load persistent tool approval hashes."""
        if os.path.exists(self._APPROVED_FILE):
            try:
                with open(self._APPROVED_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, ValueError):
                pass
        return {}

    def _save_approved_hashes(self, hashes: dict) -> None:
        """Persist tool approval hashes."""
        with open(self._APPROVED_FILE, "w") as f:
            json.dump(hashes, f, ensure_ascii=False)

    # ----------------------------------------------------------
    # Module loading
    # ----------------------------------------------------------

    def _load_module(self, filename: str, first_load: bool = False):
        """Load a single .py tool file. Returns (schema, func) or None."""
        filepath = os.path.join(self.tools_dir, filename)
        module_name = filename[:-3]

        # Read file once to prevent TOCTOU
        try:
            with open(filepath, "rb") as f:
                raw = f.read()
        except (OSError, IOError):
            return None
        content = raw.decode("utf-8", errors="replace")

        # Security scan: regex + AST + hash-based persistent approval.
        # For builtin directories (those shipping a manifest), the only way
        # to skip the scan is to match the manifest hash exactly. There is
        # no automatic "this is builtins/, trust it" shortcut anymore — see
        # the class docstring for the rationale.
        if filename not in self._approved:
            file_hash = self._file_hash(raw)
            if self._is_builtin_dir:
                expected = self._builtin_hashes.get(filename)
                if expected and expected == file_hash:
                    # Manifest entry exists and matches → trusted, no scan.
                    self._approved.add(filename)
                else:
                    # Either unregistered (no entry) or modified (hash mismatch).
                    # Run the scanner so the warning surface is identical to
                    # the user-tool flow, then block in non-interactive envs.
                    dangers = self._check_dangerous(content) + self._check_dangerous_ast(content)
                    if expected is None:
                        logger.warning(
                            f"Builtin tool {filename} is not in the manifest — "
                            f"refusing to load without explicit approval."
                        )
                    else:
                        logger.warning(
                            f"Builtin tool {filename} has been modified "
                            f"(hash mismatch with manifest) — refusing to load "
                            f"without explicit approval."
                        )
                    if dangers:
                        logger.warning(f"Dangerous patterns found in {filename}: {dangers}")
                    if not sys.stdin.isatty():
                        logger.warning(
                            f"Tool blocked: {filename} (auto-blocked in non-interactive env)"
                        )
                        return None
                    confirm = input(f"Load {filename}? (Y/N): ").strip().upper()
                    if confirm != "Y":
                        logger.warning(f"Tool blocked by user: {filename}")
                        return None
                    # NOTE: we intentionally do NOT persist this approval into
                    # the manifest from a running process. Updating the
                    # manifest is a deliberate, audited step (see
                    # scripts/regenerate_builtin_manifest.py).
            else:
                # Non-builtin directory: existing scan + persistent approval flow.
                dangers = self._check_dangerous(content) + self._check_dangerous_ast(content)
                saved = self._load_approved_hashes()
                if saved.get(filename) == file_hash:
                    pass  # Previously approved + file unchanged -> auto-approve
                else:
                    if dangers:
                        logger.warning(f"Dangerous patterns found in {filename}: {dangers}")
                    else:
                        logger.info(f"New tool {filename} found -- approval required.")
                    if not sys.stdin.isatty():
                        logger.warning(
                            f"Tool blocked: {filename} (auto-blocked in non-interactive env)"
                        )
                        return None
                    confirm = input(f"Load {filename}? (Y/N): ").strip().upper()
                    if confirm != "Y":
                        logger.warning(f"Tool blocked by user: {filename}")
                        return None
                    saved[filename] = file_hash
                    self._save_approved_hashes(saved)

        # In-memory execution (prevents TOCTOU - does not re-read from disk)
        try:
            code = compile(content, filepath, "exec")
            module = types.ModuleType(module_name)
            module.__file__ = filepath
            exec(code, module.__dict__)  # noqa: S102
        except Exception as e:
            logger.error(f"Tool load failed: {filename}: {e}")
            return None

        if hasattr(module, "SCHEMA") and hasattr(module, "main"):
            self._approved.add(filename)
            return module.SCHEMA, module.main
        return None

    def _load_all(self, first_load: bool = False) -> None:
        """Scan and load all tool files."""
        self.schemas = []
        self.functions = {}
        self._file_mtimes = self._scan_files()
        for fname in sorted(self._file_mtimes):
            result = self._load_module(fname, first_load=first_load)
            if result:
                schema, func = result
                self.schemas.append(schema)
                self.functions[schema["name"]] = func
        logger.info(f"Loaded {len(self.functions)} tool(s): {', '.join(self.functions.keys())}")

    # ----------------------------------------------------------
    # Hot reload
    # ----------------------------------------------------------

    def reload_if_changed(self) -> bool:
        """Detect file changes and reload if needed. Returns True if reloaded."""
        current = self._scan_files()
        if current == self._file_mtimes:
            return False

        added = set(current) - set(self._file_mtimes)
        removed = set(self._file_mtimes) - set(current)
        modified = {
            f for f in set(current) & set(self._file_mtimes)
            if current[f] != self._file_mtimes[f]
        }

        if added:
            logger.info(f"New tools detected: {', '.join(added)}")
        if removed:
            logger.info(f"Tools removed: {', '.join(removed)}")
        if modified:
            logger.info(f"Tools modified: {', '.join(modified)}")
            # Modified files require re-approval
            self._approved -= modified

        self._load_all()
        return True

    # ----------------------------------------------------------
    # Selective loading by name whitelist
    # ----------------------------------------------------------

    def load_only(self, tool_names: list[str]) -> None:
        """Reload, keeping only tools whose schema name is in tool_names.

        Useful for agent.yaml 'tools' whitelists.

        Args:
            tool_names: List of tool names to allow (e.g. ["read_file", "write_file"]).
                        An empty list means all tools are allowed (no filtering).
        """
        if not tool_names:
            return
        self.schemas = [s for s in self.schemas if s["name"] in tool_names]
        self.functions = {k: v for k, v in self.functions.items() if k in tool_names}
        logger.info(
            f"Filtered to {len(self.functions)} tool(s) per whitelist: {', '.join(self.functions.keys())}"
        )


# ============================================================
# Tool Execution
# ============================================================

def execute_tool(tool_use, tool_mgr: ToolManager) -> dict:
    """Execute a tool call and return the result.

    Args:
        tool_use: Claude API tool_use block (must have .name, .id, .input).
        tool_mgr: ToolManager instance.

    Returns:
        dict in tool_result format.
    """
    fn = tool_mgr.functions.get(tool_use.name)
    if not fn:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use.id,
            "content": f"Error: unknown tool: {tool_use.name}",
        }

    try:
        tool_schema = next((s for s in tool_mgr.schemas if s["name"] == tool_use.name), None)
        filtered_input = (
            _filter_tool_input(tool_use.input, tool_schema) if tool_schema else tool_use.input
        )

        result = fn(**filtered_input)
    except Exception:
        result = "Error: tool execution failed"

    safe_result = (
        str(result)
        .replace("[TOOL OUTPUT]", "[TOOL_OUTPUT]")
        .replace("[/TOOL OUTPUT]", "[/TOOL_OUTPUT]")
    )
    return {
        "type": "tool_result",
        "tool_use_id": tool_use.id,
        "content": f"[TOOL OUTPUT]\n{safe_result}\n[/TOOL OUTPUT]",
    }
