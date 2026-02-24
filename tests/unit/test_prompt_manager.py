"""Unit tests for PromptManager — ``src.ai.prompt_manager``."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.ai.prompt_manager import PromptManager


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def pm() -> PromptManager:
    """Create a default PromptManager with built-in prompts."""
    return PromptManager()


# ── Test: Built-in Prompts ───────────────────────────


class TestBuiltinPrompts:
    """Tests for built-in prompt templates."""

    def test_builtins_registered(self, pm: PromptManager) -> None:
        """Built-in prompts are automatically available."""
        prompts = pm.list_prompts()
        assert "plan_steps" in prompts
        assert "select_element" in prompts
        assert "fix_selector" in prompts

    def test_builtin_versions(self, pm: PromptManager) -> None:
        """Each built-in has at least v1."""
        prompts = pm.list_prompts()
        for name in ("plan_steps", "select_element", "fix_selector"):
            assert "v1" in prompts[name]

    def test_get_plan_steps_default(self, pm: PromptManager) -> None:
        """plan_steps template renders with instruction variable."""
        result = pm.get_prompt("plan_steps", instruction="Search for laptops")
        assert "Search for laptops" in result
        assert "JSON" in result

    def test_get_select_element_default(self, pm: PromptManager) -> None:
        """select_element template renders with candidates and intent."""
        result = pm.get_prompt(
            "select_element",
            candidates='[{"eid": "btn-1"}]',
            intent="click search",
        )
        assert "click search" in result
        assert "btn-1" in result

    def test_get_fix_selector_default(self, pm: PromptManager) -> None:
        """fix_selector template renders with all expected variables."""
        result = pm.get_prompt(
            "fix_selector",
            failed_selector="#old-btn",
            page_url="https://example.com",
            page_title="Test Page",
            visible_text="Hello World",
            elements='[{"eid": "new-btn"}]',
        )
        assert "#old-btn" in result
        assert "https://example.com" in result
        assert "Test Page" in result


# ── Test: Variable Substitution ──────────────────────


class TestVariableSubstitution:
    """Tests for template variable substitution."""

    def test_missing_variable_safe_substitute(self, pm: PromptManager) -> None:
        """Missing variables are left as $variable placeholders (safe_substitute)."""
        result = pm.get_prompt("plan_steps")  # no instruction= kwarg
        assert "$instruction" in result

    def test_extra_variables_ignored(self, pm: PromptManager) -> None:
        """Extra variables not in template are silently ignored."""
        result = pm.get_prompt(
            "plan_steps",
            instruction="test",
            extra_var="should be ignored",
        )
        assert "test" in result
        assert "should be ignored" not in result

    def test_special_characters_in_value(self, pm: PromptManager) -> None:
        """Special characters in substitution values are preserved."""
        result = pm.get_prompt(
            "plan_steps",
            instruction='Search for "laptop" with $1000 budget & free shipping',
        )
        assert '"laptop"' in result
        assert "$1000" in result
        assert "& free shipping" in result


# ── Test: Registration ───────────────────────────────


class TestRegistration:
    """Tests for prompt registration."""

    def test_register_new_prompt(self, pm: PromptManager) -> None:
        """Can register a brand new prompt."""
        pm.register_prompt("custom", "Hello $user", "v1")
        result = pm.get_prompt("custom", user="World")
        assert result == "Hello World"

    def test_register_multiple_versions(self, pm: PromptManager) -> None:
        """Can register multiple versions of the same prompt."""
        pm.register_prompt("greet", "Hi $user", "v1")
        pm.register_prompt("greet", "Hello $user!", "v2")

        v1 = pm.get_prompt("greet", version="v1", user="Alice")
        v2 = pm.get_prompt("greet", version="v2", user="Alice")

        assert v1 == "Hi Alice"
        assert v2 == "Hello Alice!"

    def test_latest_version_is_most_recent(self, pm: PromptManager) -> None:
        """'latest' resolves to the most recently registered version."""
        pm.register_prompt("test", "Version 1", "v1")
        pm.register_prompt("test", "Version 2", "v2")

        result = pm.get_prompt("test", version="latest")
        assert result == "Version 2"

    def test_register_overrides_existing_version(self, pm: PromptManager) -> None:
        """Re-registering the same name+version replaces the template."""
        pm.register_prompt("test", "Old template", "v1")
        pm.register_prompt("test", "New template", "v1")
        result = pm.get_prompt("test", version="v1")
        assert result == "New template"


# ── Test: Versioning ─────────────────────────────────


class TestVersioning:
    """Tests for version retrieval."""

    def test_get_specific_version(self, pm: PromptManager) -> None:
        """Can retrieve a specific version."""
        result = pm.get_prompt("plan_steps", version="v1", instruction="test")
        assert "test" in result

    def test_unknown_prompt_raises(self, pm: PromptManager) -> None:
        """KeyError for unknown prompt name."""
        with pytest.raises(KeyError, match="Unknown prompt"):
            pm.get_prompt("nonexistent")

    def test_unknown_version_raises(self, pm: PromptManager) -> None:
        """KeyError for unknown version."""
        with pytest.raises(KeyError, match="Unknown version"):
            pm.get_prompt("plan_steps", version="v999")

    def test_list_prompts_shows_all(self, pm: PromptManager) -> None:
        """list_prompts returns all registered names and versions."""
        pm.register_prompt("extra", "test", "v1")
        pm.register_prompt("extra", "test2", "v2")
        prompts = pm.list_prompts()
        assert "extra" in prompts
        assert prompts["extra"] == ["v1", "v2"]


# ── Test: File Loading ───────────────────────────────


class TestFileLoading:
    """Tests for loading prompts from a directory."""

    def test_load_from_directory(self, tmp_path: Path) -> None:
        """Loads prompt files from a directory structure."""
        # Create directory structure
        prompt_dir = tmp_path / "custom_prompt"
        prompt_dir.mkdir()
        (prompt_dir / "v1.txt").write_text("File prompt v1: $var", encoding="utf-8")
        (prompt_dir / "v2.txt").write_text("File prompt v2: $var", encoding="utf-8")

        pm = PromptManager(prompts_dir=tmp_path)
        result = pm.get_prompt("custom_prompt", version="v2", var="hello")
        assert result == "File prompt v2: hello"

    def test_file_prompts_coexist_with_builtins(self, tmp_path: Path) -> None:
        """File-loaded prompts do not remove built-in prompts."""
        prompt_dir = tmp_path / "extra"
        prompt_dir.mkdir()
        (prompt_dir / "v1.txt").write_text("Extra", encoding="utf-8")

        pm = PromptManager(prompts_dir=tmp_path)
        prompts = pm.list_prompts()
        assert "plan_steps" in prompts
        assert "extra" in prompts

    def test_nonexistent_dir_handled(self) -> None:
        """Non-existent prompts_dir does not raise."""
        pm = PromptManager(prompts_dir=Path("/tmp/nonexistent_prompt_dir_xyz"))
        # Built-ins should still be present
        assert "plan_steps" in pm.list_prompts()

    def test_file_overrides_builtin_version(self, tmp_path: Path) -> None:
        """File-loaded prompt version overrides a built-in with the same name+version."""
        prompt_dir = tmp_path / "plan_steps"
        prompt_dir.mkdir()
        (prompt_dir / "v1.txt").write_text(
            "Custom plan: $instruction", encoding="utf-8"
        )

        pm = PromptManager(prompts_dir=tmp_path)
        result = pm.get_prompt("plan_steps", version="v1", instruction="test")
        assert result == "Custom plan: test"
