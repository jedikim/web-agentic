"""Unit tests for the patch validator module."""
from __future__ import annotations

from src.evolution.patch_validator import (
    validate_patch,
    validate_python_syntax,
)

# ── validate_patch ──────────────────────────────────


def test_valid_modify_patch_passes() -> None:
    result = validate_patch({
        "file_path": "src/core/executor.py",
        "change_type": "modify",
        "new_content": "# updated code",
    })
    assert result.valid is True
    assert result.errors == []


def test_valid_create_patch_passes() -> None:
    result = validate_patch({
        "file_path": "src/new_module.py",
        "change_type": "create",
        "new_content": "print('hello')",
    })
    assert result.valid is True
    assert result.errors == []


def test_valid_delete_patch_passes() -> None:
    """Delete patches do not require new_content."""
    result = validate_patch({
        "file_path": "src/obsolete.py",
        "change_type": "delete",
    })
    assert result.valid is True
    assert result.errors == []


def test_missing_file_path_fails() -> None:
    result = validate_patch({
        "change_type": "modify",
        "new_content": "# code",
    })
    assert result.valid is False
    assert any("file_path" in e for e in result.errors)


def test_invalid_change_type_fails() -> None:
    result = validate_patch({
        "file_path": "src/foo.py",
        "change_type": "rename",
        "new_content": "# code",
    })
    assert result.valid is False
    assert any("change_type" in e for e in result.errors)


def test_missing_new_content_for_modify_fails() -> None:
    result = validate_patch({
        "file_path": "src/foo.py",
        "change_type": "modify",
    })
    assert result.valid is False
    assert any("new_content" in e for e in result.errors)


def test_empty_patch_fails() -> None:
    result = validate_patch({})
    assert result.valid is False
    assert len(result.errors) >= 2  # file_path + change_type


# ── validate_python_syntax ──────────────────────────


def test_python_syntax_valid() -> None:
    code = "def hello():\n    return 'world'\n"
    result = validate_python_syntax(code)
    assert result.valid is True
    assert result.errors == []


def test_python_syntax_error_detected() -> None:
    code = "def hello(\n    return 'world'\n"
    result = validate_python_syntax(code)
    assert result.valid is False
    assert any("Syntax error" in e for e in result.errors)
