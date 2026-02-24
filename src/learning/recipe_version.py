"""Recipe Versioning — immutable selector recipe with patch-based updates.

Manages versioned selector recipes for workflows.  Each recipe maps
logical selector keys to CSS selectors with timestamps.  Updates are
applied through JSON-Patch-style operations, and each application
produces a new recipe with an incremented version number.

Usage::

    from src.learning.recipe_version import (
        SelectorRecipe,
        SelectorRecipeEntry,
        SelectorPatch,
        SelectorPatchOperation,
        apply_selector_patch,
        next_recipe_version,
    )

    recipe = SelectorRecipe(
        workflow_id="checkout",
        version="v001",
        selectors={"login_btn": SelectorRecipeEntry(css="#login", updated_at="2024-01-01")},
    )
    patch = SelectorPatch(
        target="checkout",
        operations=[
            SelectorPatchOperation(op="add", path="/selectors/cart_btn", value={"css": ".cart"}),
        ],
    )
    new_recipe = apply_selector_patch(recipe, patch, updated_at="2024-01-02")
    # new_recipe.version == "v002"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# ── Types ────────────────────────────────────────────

SelectorPatchOp = Literal["add", "replace", "remove"]

_VERSION_RE = re.compile(r"^v\d+$")


# ── Dataclasses ──────────────────────────────────────


@dataclass(frozen=True)
class SelectorRecipeEntry:
    """A single selector entry within a recipe.

    Attributes:
        css: The CSS selector string.
        updated_at: ISO-8601 timestamp of last update.
    """

    css: str
    updated_at: str


@dataclass
class SelectorRecipe:
    """A versioned collection of named selectors for a workflow.

    Attributes:
        workflow_id: Identifier of the workflow this recipe belongs to.
        version: Version string in ``vNNN`` format (e.g. ``v001``).
        selectors: Mapping of logical name to ``SelectorRecipeEntry``.
    """

    workflow_id: str
    version: str
    selectors: dict[str, SelectorRecipeEntry] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectorPatchOperation:
    """A single patch operation to apply to a recipe's selectors.

    Attributes:
        op: Operation type — ``add``, ``replace``, or ``remove``.
        path: JSON-Pointer-style path (must start with ``/selectors/``).
        value: Selector data for ``add``/``replace`` ops.  Must contain ``css``.
    """

    op: SelectorPatchOp
    path: str
    value: dict[str, str] | None = None


@dataclass(frozen=True)
class SelectorPatch:
    """A batch of patch operations targeting a recipe.

    Attributes:
        target: The workflow ID this patch targets.
        operations: Ordered list of operations to apply.
    """

    target: str
    operations: list[SelectorPatchOperation] = field(default_factory=list)


# ── Helper ───────────────────────────────────────────


def _selector_key_from_path(path: str) -> str:
    """Extract the selector key from a JSON-Pointer path.

    Args:
        path: Path like ``/selectors/login_btn``.

    Returns:
        The key portion (e.g. ``login_btn``).
    """
    prefix = "/selectors/"
    return path[len(prefix):]


# ── Public API ───────────────────────────────────────


def next_recipe_version(version: str) -> str:
    """Increment a recipe version string.

    The version must match the pattern ``vN`` where *N* is one or more
    digits (e.g. ``v001``, ``v099``, ``v1``).  The returned version is
    zero-padded to at least three digits.

    Args:
        version: Current version string.

    Returns:
        The next version string.

    Raises:
        ValueError: If *version* does not match the ``vN`` format.
    """
    if not _VERSION_RE.match(version):
        raise ValueError(f"invalid version format: {version}")
    n = int(version[1:]) + 1
    return f"v{str(n).zfill(3)}"


def validate_selector_patch(
    patch: SelectorPatch,
) -> tuple[bool, list[str]]:
    """Validate a selector patch for structural correctness.

    Checks:
        * Operations list is not empty.
        * Each operation has a ``path`` starting with ``/selectors/``.
        * ``add`` and ``replace`` operations must include a ``value`` dict
          containing at least a ``css`` key.

    Args:
        patch: The patch to validate.

    Returns:
        A tuple of ``(is_valid, error_messages)``.
    """
    errors: list[str] = []

    if not patch.operations:
        errors.append("operations must not be empty")
        return (False, errors)

    for i, op in enumerate(patch.operations):
        if not op.path.startswith("/selectors/"):
            errors.append(
                f"operation[{i}]: path must start with /selectors/, got {op.path!r}"
            )

        if op.op in ("add", "replace"):
            if op.value is None:
                errors.append(
                    f"operation[{i}]: {op.op} requires a value"
                )
            elif "css" not in op.value:
                errors.append(
                    f"operation[{i}]: {op.op} value must contain 'css' key"
                )

    return (len(errors) == 0, errors)


def apply_selector_patch(
    recipe: SelectorRecipe,
    patch: SelectorPatch,
    updated_at: str,
) -> SelectorRecipe:
    """Apply a selector patch to a recipe, producing a new versioned recipe.

    The original recipe is not mutated.  A new ``SelectorRecipe`` is
    returned with the patch applied and the version bumped.

    Args:
        recipe: The current recipe to patch.
        patch: The set of operations to apply.
        updated_at: ISO-8601 timestamp to set on modified entries.

    Returns:
        A new ``SelectorRecipe`` with updated selectors and version.

    Raises:
        ValueError: If the patch fails validation.
    """
    valid, errors = validate_selector_patch(patch)
    if not valid:
        raise ValueError(f"invalid selector patch: {'; '.join(errors)}")

    next_selectors = dict(recipe.selectors)

    for operation in patch.operations:
        key = _selector_key_from_path(operation.path)

        if operation.op == "remove":
            next_selectors.pop(key, None)
            continue

        # add or replace
        assert operation.value is not None  # guaranteed by validation
        next_selectors[key] = SelectorRecipeEntry(
            css=operation.value["css"],
            updated_at=updated_at,
        )

    return SelectorRecipe(
        workflow_id=recipe.workflow_id,
        version=next_recipe_version(recipe.version),
        selectors=next_selectors,
    )
