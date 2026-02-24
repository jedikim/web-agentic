"""Prompt Version Management for LLM calls.

Manages prompt templates with versioning, providing built-in defaults
for web automation tasks (plan_steps, select_element, fix_selector).
"""
from __future__ import annotations

import logging
from pathlib import Path
from string import Template

logger = logging.getLogger(__name__)

# ── Built-in prompt templates ─────────────────────────

_BUILTIN_PROMPTS: dict[str, dict[str, str]] = {
    "plan_steps": {
        "v1": (
            "You are a web automation assistant. Your task is to decompose a natural "
            "language instruction into a sequence of concrete automation steps.\n\n"
            "Instruction: $instruction\n\n"
            "Return a JSON array of step objects. Each step object must have:\n"
            '- "step_id": a unique string identifier (e.g., "step_1")\n'
            '- "intent": a short description of what this step does\n'
            '- "node_type": one of "action", "extract", "decide", "verify", '
            '"branch", "loop", "wait", "recover", "handoff"\n'
            '- "selector": CSS selector or null if not known\n'
            '- "arguments": array of string arguments (can be empty)\n'
            '- "max_attempts": integer, default 3\n'
            '- "timeout_ms": integer, default 10000\n\n'
            "Example output:\n"
            "[\n"
            '  {"step_id": "step_1", "intent": "Navigate to search page", '
            '"node_type": "action", "selector": null, "arguments": '
            '["https://example.com"], "max_attempts": 3, "timeout_ms": 10000},\n'
            '  {"step_id": "step_2", "intent": "Type search query", '
            '"node_type": "action", "selector": "#search-input", '
            '"arguments": ["laptop"], "max_attempts": 3, "timeout_ms": 10000}\n'
            "]\n\n"
            "Constraints:\n"
            "- Output MUST be valid JSON — no markdown, no comments, no code.\n"
            "- Do NOT generate code. Only produce the JSON step list.\n"
            "- Be specific: each step should be a single, atomic browser action.\n"
            "- Include a confidence score in a top-level wrapper if unsure:\n"
            '  {"confidence": 0.85, "steps": [...]}'
        ),
    },
    "plan_steps_with_context": {
        "v1": (
            "You are a web automation assistant. You are currently viewing a web page.\n\n"
            "Current page:\n"
            "- URL: $page_url\n"
            "- Title: $page_title\n"
            "- Visible text (excerpt): $visible_text\n\n"
            "User's task: $instruction\n\n"
            "Decompose this task into concrete browser automation steps. "
            "Consider what you see on the current page to decide the next actions.\n\n"
            "IMPORTANT:\n"
            "- You MUST cover ALL parts of the user's task. If the task has multiple sub-goals "
            "(e.g. 'search X AND sort by Y'), generate steps for EVERY sub-goal.\n"
            "- After submitting a search/form, add a 'wait' step (2000-3000ms) for results to load.\n"
            "- After results load, continue with remaining actions (sorting, filtering, clicking, etc.).\n\n"
            "Each step must specify:\n"
            '- "step_id": unique string (e.g. "step_1")\n'
            '- "intent": what this step does in natural language\n'
            '- "action": one of "goto", "click", "type", "press_key", "scroll", "wait"\n'
            '- "selector": CSS selector if known, or null\n'
            '- "arguments": array of strings (URL for goto, text for type, key for press_key, ms for wait)\n'
            '- "verify": optional verification object e.g. {"type": "url_contains", "value": "query="}\n\n'
            "Return JSON:\n"
            '{"confidence": 0.9, "steps": [...]}\n\n'
            "Constraints:\n"
            "- Output MUST be valid JSON only.\n"
            "- Each step = one atomic browser action.\n"
            "- For search: type into search input, then press Enter or click search button, then wait for results.\n"
            "- Be specific about what element to interact with.\n"
            "- Do NOT stop after the first sub-goal. Complete the ENTIRE task."
        ),
    },
    "select_element": {
        "v1": (
            "You are a web automation assistant. Given a list of interactive elements "
            "and a user intent, select the single best element to interact with.\n\n"
            "Intent: $intent\n\n"
            "Candidate elements (JSON):\n$candidates\n\n"
            "Return a JSON object with:\n"
            '- "eid": the element ID of the best match\n'
            '- "confidence": your confidence score (0.0 to 1.0)\n'
            '- "reasoning": a brief explanation of why this element was chosen\n\n'
            "Example output:\n"
            '{"eid": "btn-submit", "confidence": 0.95, '
            '"reasoning": "Button text matches the submit intent"}\n\n'
            "Constraints:\n"
            "- Output MUST be valid JSON — no markdown, no comments, no code.\n"
            "- Select exactly one element.\n"
            "- Prefer visible elements over hidden ones.\n"
            "- Prefer elements whose text or role closely matches the intent."
        ),
    },
    "fix_selector": {
        "v1": (
            "You are a web automation assistant. A CSS selector failed to find an "
            "element on the page. Suggest a fixed selector based on the page context.\n\n"
            "Failed selector: $failed_selector\n"
            "Page URL: $page_url\n"
            "Page title: $page_title\n"
            "Visible text excerpt: $visible_text\n"
            "Available elements (JSON):\n$elements\n\n"
            "Return a JSON object with:\n"
            '- "patch_type": "selector_fix"\n'
            '- "target": the original failed selector\n'
            '- "data": {"new_selector": "...", "strategy": "..."}\n'
            '- "confidence": your confidence score (0.0 to 1.0)\n\n'
            "Example output:\n"
            '{"patch_type": "selector_fix", "target": "#old-btn", '
            '"data": {"new_selector": ".new-btn-class", '
            '"strategy": "class-based"}, "confidence": 0.8}\n\n'
            "Constraints:\n"
            "- Output MUST be valid JSON — no markdown, no comments, no code.\n"
            "- Do NOT generate code. Only produce the JSON patch.\n"
            "- The new selector must be a valid CSS selector."
        ),
    },
}


class PromptManager:
    """Manages prompt templates for LLM calls with versioning.

    Built-in prompts are registered by default. Additional prompts can be
    registered at runtime or loaded from a directory of template files.

    Attributes:
        _prompts: Mapping of prompt name -> version -> template string.
        _latest_versions: Mapping of prompt name -> latest version string.
    """

    def __init__(self, prompts_dir: Path | None = None) -> None:
        """Initialise with optional directory of template files.

        Args:
            prompts_dir: Optional directory containing .txt template files
                organised as ``{name}/{version}.txt``. Built-in prompts
                are always registered regardless.
        """
        self._prompts: dict[str, dict[str, str]] = {}
        self._latest_versions: dict[str, str] = {}

        # Register built-in prompts
        for name, versions in _BUILTIN_PROMPTS.items():
            for version, template in versions.items():
                self.register_prompt(name, template, version)

        # Load from directory if provided
        if prompts_dir is not None:
            self._load_from_directory(prompts_dir)

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
