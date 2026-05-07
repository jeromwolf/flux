"""
flux.safety.scanner - Secret masking, logging, and dangerous pattern detection.

Extracted from openclaw.security for the flux namespace.
"""

import re
import ast
from datetime import datetime

# ============================================================
# Secret Masking
# ============================================================

# Log masking patterns - covers common API key formats
_SECRET_RE = re.compile(
    r"(sk-ant-[a-zA-Z0-9_-]+|AIza[a-zA-Z0-9_-]+|sk-[a-zA-Z0-9_-]{20,}"
    r"|ghp_[a-zA-Z0-9]{36,}|glpat-[a-zA-Z0-9_-]{20,}"
    r"|xox[bpsa]-[a-zA-Z0-9-]{10,})"
)


def _mask_secrets(text: str) -> str:
    """Replace known secret patterns with [REDACTED]."""
    return _SECRET_RE.sub("[REDACTED]", str(text))


def log(f, role: str, message: str) -> None:
    """Write a masked log entry to file f with role and timestamp."""
    masked = _mask_secrets(message)
    f.write(f"## {role} ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n\n{masked}\n\n")
    f.flush()


# ============================================================
# Dangerous Pattern Detection
# ============================================================

_DANGEROUS_PATTERNS = [
    r"\bos\.system\b", r"\bos\.popen\b", r"\bos\.exec\w*\b",
    r"\bsubprocess\b", r"\beval\s*\(", r"\bexec\s*\(",
    r"\b__import__\b", r"\bcompile\s*\(", r"\bglobals\s*\(", r"\bgetattr\s*\(",
    r"\bimportlib\b", r"\bctypes\b", r"\bpickle\b",
    r"\bshutil\.rmtree\b", r"\bsocket\b",
    r"\bbase64\b", r"\bcodecs\b", r"\bbinascii\b",
    r"__builtins__", r"__subclasses__",
    r"\bos\.remove\b", r"\bos\.unlink\b", r"\bos\.rename\b", r"\bos\.chmod\b",
    r"\bos\.listdir\b", r"\bos\.walk\b", r"\bos\.scandir\b",
    r"\bopen\s*\(",
    r"\bvars\s*\(", r"\btype\s*\(", r"\bbreakpoint\s*\(",
    r"\bdir\s*\(", r"\blocals\s*\(",
]
_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS))


# ============================================================
# Tool File Security Scanner
# ============================================================

def scan_tool_file(path: str) -> list[str]:
    """Scan a Python file for dangerous patterns.

    Performs both regex-based and AST-based analysis to detect potentially
    unsafe constructs (eval, exec, subprocess, os.system, etc.).

    Args:
        path: Absolute or relative path to a Python source file.

    Returns:
        List of security warning strings. Empty list means no issues found.
    """
    warnings: list[str] = []

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except (OSError, IOError) as e:
        return [f"Could not read file: {e}"]

    # --- Regex pass ---
    regex_hits = _DANGEROUS_RE.findall(source)
    for hit in regex_hits:
        warnings.append(f"[regex] dangerous pattern: {hit!r}")

    # --- AST pass ---
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
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        warnings.append(f"[ast] SyntaxError: {e}")
        return warnings

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _BLOCKED_IMPORTS:
                    warnings.append(f"[ast] blocked import: {alias.name} (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in _BLOCKED_IMPORTS:
                warnings.append(f"[ast] blocked import: from {node.module} (line {node.lineno})")
        elif isinstance(node, ast.Attribute) and node.attr in _BLOCKED_ATTRS:
            warnings.append(f"[ast] blocked attribute access: {node.attr} (line {node.lineno})")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                call_name = f"{node.func.value.id}.{node.func.attr}"
                if call_name in _BLOCKED_CALLS:
                    warnings.append(f"[ast] blocked call: {call_name}() (line {node.lineno})")
            elif isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_BUILTINS:
                warnings.append(
                    f"[ast] blocked builtin: {node.func.id}() (line {node.lineno})"
                )

    return warnings
