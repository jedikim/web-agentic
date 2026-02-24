"""Patch validator — validates LLM-generated code changes before application.

Pure validation functions that check:
1. Patch structure (required fields, valid change_type)
2. Python syntax (via ast.parse)
"""
from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class PatchValidationResult:
    """Result of a patch validation check."""

    valid: bool
    errors: list[str]


VALID_CHANGE_TYPES = {"modify", "create", "delete"}


def validate_patch(patch: dict[str, object]) -> PatchValidationResult:
    """Validate patch structure.

    Required fields: file_path (non-empty str), change_type (modify|create|delete).
    For modify/create: new_content required (non-empty str).
    For delete: new_content not required.

    Args:
        patch: Dict with file_path, change_type, and optionally new_content.

    Returns:
        PatchValidationResult with valid=True if all checks pass.
    """
    errors: list[str] = []

    # Check file_path
    fp = patch.get("file_path")
    if not fp or not isinstance(fp, str):
        errors.append("file_path is required and must be non-empty string")

    # Check change_type
    ct = patch.get("change_type")
    if ct not in VALID_CHANGE_TYPES:
        errors.append(f"change_type must be one of {VALID_CHANGE_TYPES}, got '{ct}'")

    # Check new_content for modify/create
    if ct in ("modify", "create"):
        nc = patch.get("new_content")
        if not nc or not isinstance(nc, str):
            errors.append("new_content is required for modify/create")

    return PatchValidationResult(valid=len(errors) == 0, errors=errors)


def validate_python_syntax(code: str) -> PatchValidationResult:
    """Validate Python syntax using ast.parse.

    Args:
        code: Python source code string to validate.

    Returns:
        PatchValidationResult with valid=True if code parses successfully.
    """
    try:
        ast.parse(code)
        return PatchValidationResult(valid=True, errors=[])
    except SyntaxError as e:
        return PatchValidationResult(valid=False, errors=[f"Syntax error: {e}"])
