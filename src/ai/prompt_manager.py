"""Prompt Version Management for LLM calls.

Manages prompt templates with versioning, loading from external files
in ``config/prompts/`` for web automation tasks.
"""
from __future__ import annotations

import logging
from pathlib import Path
from string import Template

logger = logging.getLogger(__name__)

# Default prompts directory (relative to project root)
_DEFAULT_PROMPTS_DIR = Path("config/prompts")


class PromptManager:
    """Manages prompt templates for LLM calls with versioning.

    Built-in prompts are registered by default. Additional prompts can be
    registered at runtime or loaded from a directory of template files.

    Attributes:
        _prompts: Mapping of prompt name -> version -> template string.
        _latest_versions: Mapping of prompt name -> latest version string.
    """

    def __init__(self, prompts_dir: Path | None = None) -> None:
        """Initialise with a directory of template files.

        Args:
            prompts_dir: Directory containing .txt template files
                organised as ``{name}/{version}.txt``. Defaults to
                ``config/prompts/`` relative to the project root.
        """
        self._prompts: dict[str, dict[str, str]] = {}
        self._latest_versions: dict[str, str] = {}

        # Load from directory (default: config/prompts/)
        resolved_dir = prompts_dir if prompts_dir is not None else _DEFAULT_PROMPTS_DIR
        self._load_from_directory(resolved_dir)

    def get_prompt(self, name: str, version: str = "latest", **kwargs: str) -> str:
        """Retrieve and render a prompt template.

        Args:
            name: Prompt template name (e.g., "plan_steps").
            version: Template version. Use "latest" for the most recent.
            **kwargs: Template variable substitutions.

        Returns:
            Rendered prompt string with variables substituted.

        Raises:
            KeyError: If the prompt name or version is not found.
        """
        if name not in self._prompts:
            raise KeyError(f"Unknown prompt: {name!r}")

        if version == "latest":
            version = self._latest_versions[name]

        versions = self._prompts[name]
        if version not in versions:
            raise KeyError(
                f"Unknown version {version!r} for prompt {name!r}. "
                f"Available: {sorted(versions.keys())}"
            )

        template = Template(versions[version])
        return template.safe_substitute(**kwargs)

    def register_prompt(self, name: str, template: str, version: str) -> None:
        """Register a new prompt template version.

        Args:
            name: Prompt template name.
            template: Template string using ``$variable`` placeholders.
            version: Version identifier (e.g., "v1", "v2").
        """
        if name not in self._prompts:
            self._prompts[name] = {}

        self._prompts[name][version] = template
        self._latest_versions[name] = version
        logger.debug("Registered prompt %r version %r", name, version)

    def list_prompts(self) -> dict[str, list[str]]:
        """List all registered prompts and their versions.

        Returns:
            Dict mapping prompt name to list of version strings.
        """
        return {name: sorted(versions.keys()) for name, versions in self._prompts.items()}

    def _load_from_directory(self, prompts_dir: Path) -> None:
        """Load prompt templates from a directory structure.

        Expected layout::

            prompts_dir/
                plan_steps/
                    v1.txt
                    v2.txt
                select_element/
                    v1.txt

        Args:
            prompts_dir: Root directory containing prompt subdirectories.
        """
        if not prompts_dir.is_dir():
            logger.warning("Prompts directory does not exist: %s", prompts_dir)
            return

        for name_dir in sorted(prompts_dir.iterdir()):
            if not name_dir.is_dir():
                continue
            name = name_dir.name
            for template_file in sorted(name_dir.glob("*.txt")):
                version = template_file.stem
                template = template_file.read_text(encoding="utf-8")
                self.register_prompt(name, template, version)
                logger.debug("Loaded prompt %s/%s from file", name, version)
