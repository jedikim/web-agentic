"""Tests for Recipe Versioning — version bumping, patch validation, and application.

Covers version formatting, patch validation rules, and all patch operation
types (add, replace, remove) including version bumping on apply.
"""
from __future__ import annotations

import pytest

from src.learning.recipe_version import (
    SelectorPatch,
    SelectorPatchOperation,
    SelectorRecipe,
    SelectorRecipeEntry,
    apply_selector_patch,
    next_recipe_version,
    validate_selector_patch,
)

# ── Version Tests ────────────────────────────────────


class TestNextRecipeVersion:
    """Tests for next_recipe_version."""

    def test_next_version_basic(self) -> None:
        """v001 should become v002."""
        assert next_recipe_version("v001") == "v002"

    def test_next_version_padding(self) -> None:
        """v099 should become v100 (no truncation)."""
        assert next_recipe_version("v099") == "v100"

    def test_next_version_invalid_format(self) -> None:
        """Non-vN format should raise ValueError."""
        with pytest.raises(ValueError, match="invalid version format"):
            next_recipe_version("1.0.0")

    def test_next_version_invalid_empty(self) -> None:
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError, match="invalid version format"):
            next_recipe_version("")

    def test_next_version_invalid_no_digits(self) -> None:
        """'v' alone should raise ValueError."""
        with pytest.raises(ValueError, match="invalid version format"):
            next_recipe_version("v")

    def test_next_version_single_digit(self) -> None:
        """v1 should become v002 (zero-padded to 3 digits)."""
        assert next_recipe_version("v1") == "v002"

    def test_next_version_large_number(self) -> None:
        """v999 should become v1000."""
        assert next_recipe_version("v999") == "v1000"


# ── Validation Tests ─────────────────────────────────


class TestValidateSelectorPatch:
    """Tests for validate_selector_patch."""

    def test_validate_patch_valid(self) -> None:
        """A well-formed patch should pass validation."""
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="add",
                    path="/selectors/login_btn",
                    value={"css": "#login"},
                ),
            ],
        )
        valid, errors = validate_selector_patch(patch)
        assert valid is True
        assert errors == []

    def test_validate_patch_empty_operations(self) -> None:
        """An empty operations list should fail."""
        patch = SelectorPatch(target="checkout", operations=[])
        valid, errors = validate_selector_patch(patch)
        assert valid is False
        assert any("empty" in e for e in errors)

    def test_validate_patch_missing_value_for_add(self) -> None:
        """An add op without value should fail."""
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="add",
                    path="/selectors/btn",
                    value=None,
                ),
            ],
        )
        valid, errors = validate_selector_patch(patch)
        assert valid is False
        assert any("requires a value" in e for e in errors)

    def test_validate_patch_missing_css_key(self) -> None:
        """A replace op with value missing 'css' should fail."""
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="replace",
                    path="/selectors/btn",
                    value={"xpath": "//button"},
                ),
            ],
        )
        valid, errors = validate_selector_patch(patch)
        assert valid is False
        assert any("'css' key" in e for e in errors)

    def test_validate_patch_invalid_path(self) -> None:
        """A path not starting with /selectors/ should fail."""
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="add",
                    path="/other/btn",
                    value={"css": "#btn"},
                ),
            ],
        )
        valid, errors = validate_selector_patch(patch)
        assert valid is False
        assert any("/selectors/" in e for e in errors)

    def test_validate_patch_remove_no_value_ok(self) -> None:
        """A remove op without value should pass."""
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="remove",
                    path="/selectors/old_btn",
                ),
            ],
        )
        valid, errors = validate_selector_patch(patch)
        assert valid is True
        assert errors == []


# ── Apply Patch Tests ────────────────────────────────


class TestApplySelectorPatch:
    """Tests for apply_selector_patch."""

    def _base_recipe(self) -> SelectorRecipe:
        """Create a base recipe for testing."""
        return SelectorRecipe(
            workflow_id="checkout",
            version="v001",
            selectors={
                "login_btn": SelectorRecipeEntry(
                    css="#login", updated_at="2024-01-01"
                ),
            },
        )

    def test_apply_patch_add_operation(self) -> None:
        """Adding a new selector should include it in the result."""
        recipe = self._base_recipe()
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="add",
                    path="/selectors/cart_btn",
                    value={"css": ".cart"},
                ),
            ],
        )

        result = apply_selector_patch(recipe, patch, updated_at="2024-02-01")

        assert "cart_btn" in result.selectors
        assert result.selectors["cart_btn"].css == ".cart"
        assert result.selectors["cart_btn"].updated_at == "2024-02-01"
        # Original selector preserved
        assert "login_btn" in result.selectors

    def test_apply_patch_replace_operation(self) -> None:
        """Replacing an existing selector should update its value."""
        recipe = self._base_recipe()
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="replace",
                    path="/selectors/login_btn",
                    value={"css": ".new-login"},
                ),
            ],
        )

        result = apply_selector_patch(recipe, patch, updated_at="2024-02-01")

        assert result.selectors["login_btn"].css == ".new-login"
        assert result.selectors["login_btn"].updated_at == "2024-02-01"

    def test_apply_patch_remove_operation(self) -> None:
        """Removing a selector should exclude it from the result."""
        recipe = self._base_recipe()
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="remove",
                    path="/selectors/login_btn",
                ),
            ],
        )

        result = apply_selector_patch(recipe, patch, updated_at="2024-02-01")

        assert "login_btn" not in result.selectors

    def test_apply_patch_bumps_version(self) -> None:
        """Applying a patch should increment the version."""
        recipe = self._base_recipe()
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="add",
                    path="/selectors/new_btn",
                    value={"css": "#new"},
                ),
            ],
        )

        result = apply_selector_patch(recipe, patch, updated_at="2024-02-01")

        assert result.version == "v002"
        assert result.workflow_id == "checkout"

    def test_apply_patch_does_not_mutate_original(self) -> None:
        """The original recipe should remain unchanged after patching."""
        recipe = self._base_recipe()
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="add",
                    path="/selectors/new_btn",
                    value={"css": "#new"},
                ),
            ],
        )

        apply_selector_patch(recipe, patch, updated_at="2024-02-01")

        assert "new_btn" not in recipe.selectors
        assert recipe.version == "v001"

    def test_apply_patch_invalid_raises(self) -> None:
        """Applying an invalid patch should raise ValueError."""
        recipe = self._base_recipe()
        patch = SelectorPatch(target="checkout", operations=[])

        with pytest.raises(ValueError, match="invalid selector patch"):
            apply_selector_patch(recipe, patch, updated_at="2024-02-01")

    def test_apply_patch_multiple_operations(self) -> None:
        """Multiple operations in a single patch should all be applied."""
        recipe = self._base_recipe()
        patch = SelectorPatch(
            target="checkout",
            operations=[
                SelectorPatchOperation(
                    op="replace",
                    path="/selectors/login_btn",
                    value={"css": ".login-v2"},
                ),
                SelectorPatchOperation(
                    op="add",
                    path="/selectors/submit_btn",
                    value={"css": "#submit"},
                ),
            ],
        )

        result = apply_selector_patch(recipe, patch, updated_at="2024-03-01")

        assert result.selectors["login_btn"].css == ".login-v2"
        assert result.selectors["submit_btn"].css == "#submit"
        assert result.version == "v002"
