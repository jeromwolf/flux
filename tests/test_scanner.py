"""Tests for flux.safety.scanner module."""
from __future__ import annotations

import pytest

from flux.safety.scanner import _mask_secrets, scan_tool_file


# ---------------------------------------------------------------------------
# Test 1: Masks sk-ant-xxx keys
# ---------------------------------------------------------------------------

def test_mask_secrets_anthropic_key():
    text = "My key is sk-ant-api03-supersecretvalue and nothing else"
    result = _mask_secrets(text)

    assert "[REDACTED]" in result
    assert "sk-ant-" not in result


# ---------------------------------------------------------------------------
# Test 2: Masks sk-xxx OpenAI-style keys (>= 20 chars after sk-)
# ---------------------------------------------------------------------------

def test_mask_secrets_openai_key():
    # Must be at least 20 chars after "sk-"
    text = "api_key=sk-abcdefghijklmnopqrstuvwxyz1234567890"
    result = _mask_secrets(text)

    assert "[REDACTED]" in result
    assert "sk-abcdefghij" not in result


# ---------------------------------------------------------------------------
# Test 3: Leaves clean text unchanged
# ---------------------------------------------------------------------------

def test_mask_secrets_no_secrets():
    text = "Hello, world! No secrets here. Just plain text 12345."
    result = _mask_secrets(text)

    assert result == text


# ---------------------------------------------------------------------------
# Test 4: Detects eval() in code
# ---------------------------------------------------------------------------

def test_dangerous_patterns_eval(tmp_path):
    code = "result = eval(user_input)\n"
    f = tmp_path / "evil_eval.py"
    f.write_text(code, encoding="utf-8")

    warnings = scan_tool_file(str(f))

    # Should produce at least one warning mentioning eval
    assert any("eval" in w for w in warnings), f"Expected eval warning, got: {warnings}"


# ---------------------------------------------------------------------------
# Test 5: Detects exec() in code
# ---------------------------------------------------------------------------

def test_dangerous_patterns_exec(tmp_path):
    code = "exec(some_code)\n"
    f = tmp_path / "evil_exec.py"
    f.write_text(code, encoding="utf-8")

    warnings = scan_tool_file(str(f))

    assert any("exec" in w for w in warnings), f"Expected exec warning, got: {warnings}"


# ---------------------------------------------------------------------------
# Test 6: Detects subprocess import
# ---------------------------------------------------------------------------

def test_dangerous_patterns_subprocess(tmp_path):
    code = "import subprocess\nsubprocess.run(['ls'])\n"
    f = tmp_path / "evil_subprocess.py"
    f.write_text(code, encoding="utf-8")

    warnings = scan_tool_file(str(f))

    assert any("subprocess" in w for w in warnings), f"Expected subprocess warning, got: {warnings}"


# ---------------------------------------------------------------------------
# Test 7: Returns empty list for safe code
# ---------------------------------------------------------------------------

def test_scan_tool_file_clean(tmp_path):
    code = (
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
        "\n"
        "def greet(name: str) -> str:\n"
        "    return f'Hello, {name}'\n"
    )
    f = tmp_path / "clean.py"
    f.write_text(code, encoding="utf-8")

    warnings = scan_tool_file(str(f))

    assert warnings == [], f"Expected no warnings for clean code, got: {warnings}"


# ---------------------------------------------------------------------------
# Test 8: Returns warnings for dangerous code
# ---------------------------------------------------------------------------

def test_scan_tool_file_dangerous(tmp_path):
    code = (
        "import subprocess\n"
        "import pickle\n"
        "\n"
        "def run(cmd):\n"
        "    return eval(cmd)\n"
    )
    f = tmp_path / "dangerous.py"
    f.write_text(code, encoding="utf-8")

    warnings = scan_tool_file(str(f))

    assert len(warnings) >= 1, "Expected at least one warning for dangerous code"
    warning_text = " ".join(warnings)
    # At least one of the dangerous constructs should be flagged
    assert any(kw in warning_text for kw in ("subprocess", "pickle", "eval")), (
        f"Expected dangerous pattern in warnings, got: {warnings}"
    )
