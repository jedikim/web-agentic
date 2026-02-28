"""Code generator — uses Gemini 2.5 Pro to generate code fixes.

Dedicated LLM client separate from the runtime LLMPlanner to:
1. Isolate cost accounting (evolution vs runtime)
2. Always use Pro model (runtime uses Flash for cheap operations)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from src.evolution.patch_validator import validate_patch, validate_python_syntax
from src.observability.tracing import trace

logger = logging.getLogger(__name__)

# ── Cost tracking ────────────────────────────────────

DEFAULT_CODE_MODEL = os.environ.get("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview")

_COST_PER_MILLION: dict[str, dict[str, float]] = {
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.0},
    "gemini-3-pro-preview": {"input": 2.00, "output": 12.0},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
}


@dataclass
class EvolutionUsage:
    """Track LLM usage for evolution operations."""
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    calls: int = 0
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def record(self, model: str, tokens: int) -> None:
        pricing = _COST_PER_MILLION.get(model, {"input": 2.0, "output": 12.0})
        avg_per_million = (pricing["input"] + pricing["output"]) / 2
        cost = (tokens / 1_000_000) * avg_per_million
        self.total_tokens += tokens
        self.total_cost_usd += cost
        self.calls += 1
        self.call_log.append({
            "model": model, "tokens": tokens, "cost_usd": cost,
        })


# ── Code Change ──────────────────────────────────────


@dataclass
class CodeChange:
    """A single file modification proposed by the LLM."""
    file_path: str
    change_type: str  # modify | create | delete
    new_content: str | None = None
    description: str = ""


@dataclass
class GenerationResult:
    """Result of a code generation call."""
    changes: list[CodeChange]
    summary: str
    usage: EvolutionUsage


# ── Prompt Templates ─────────────────────────────────

_SYSTEM_PROMPT = """You are an expert Python developer working on the web-agentic project.
This is an adaptive web automation engine that uses LLM to control browser automation.

Key conventions:
- Python 3.11+, async/await everywhere
- Type hints required on all functions
- Google-style docstrings
- ruff for linting, mypy strict mode
- aiosqlite for DB, Playwright for browser, Google Gemini for LLM
- Keep changes minimal and focused

You will be given failure patterns from automated testing and relevant source code.
Generate the minimal code changes to fix the failures.

IMPORTANT: Output ONLY valid JSON in this exact format:
{
  "summary": "Brief description of what was changed and why",
  "changes": [
    {
      "file_path": "src/path/to/file.py",
      "change_type": "modify",
      "new_content": "...full file content...",
      "description": "What was changed in this file"
    }
  ]
}
"""

_FIX_PROMPT = """## Failure Patterns

{failure_patterns}

## Relevant Source Code

{source_code}

## Project Conventions (from CLAUDE.md)

{conventions}

## Task

Analyze the failure patterns above and generate code changes to fix them.
Focus on the most impactful fixes. Keep changes minimal.

Output your response as JSON with "summary" and "changes" fields.
"""


class EvolutionCodeGenerator:
    """Generates code fixes using Gemini 2.5 Pro."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        self._client = genai.Client(api_key=key) if key else genai.Client()
        self._model_name = model or DEFAULT_CODE_MODEL
        self.usage = EvolutionUsage()

    @trace(name="evolution-generate-fixes", as_type="generation")
    async def generate_fixes(
        self,
        failure_patterns: list[dict[str, Any]],
        relevant_files: dict[str, str] | None = None,
    ) -> GenerationResult:
        """Generate code fixes for the given failure patterns.

        Args:
            failure_patterns: List of failure pattern dicts from DB.
            relevant_files: Dict of {file_path: file_content} for context.

        Returns:
            GenerationResult with proposed changes.
        """
        # Format failure patterns
        fp_text = json.dumps(failure_patterns, indent=2, default=str)

        # Format source code
        source_parts: list[str] = []
        if relevant_files:
            for path, content in relevant_files.items():
                source_parts.append(f"### {path}\n```python\n{content}\n```")
        source_text = "\n\n".join(source_parts) if source_parts else "(no source files provided)"

        # Load conventions from CLAUDE.md
        conventions = self._load_conventions()

        prompt = _FIX_PROMPT.format(
            failure_patterns=fp_text,
            source_code=source_text,
            conventions=conventions,
        )

        response_text, tokens = await self._call_gemini(prompt)
        self.usage.record(self._model_name, tokens)

        result = self._parse_response(response_text)

        # Validate generated changes
        valid, errors = self._validate_changes(result.changes)
        if not valid:
            logger.warning("Patch validation failed, retrying once: %s", errors)
            response_text2, tokens2 = await self._call_gemini(prompt)
            self.usage.record(self._model_name, tokens2)
            result = self._parse_response(response_text2)
            valid2, errors2 = self._validate_changes(result.changes)
            if not valid2:
                logger.warning("Patch validation failed after retry: %s", errors2)

        return result

    def _validate_changes(self, changes: list[CodeChange]) -> tuple[bool, list[str]]:
        """Validate a list of CodeChanges using patch_validator.

        Args:
            changes: List of CodeChange objects to validate.

        Returns:
            Tuple of (all_valid, list_of_error_strings).
        """
        all_errors: list[str] = []
        for change in changes:
            patch_dict = {
                "file_path": change.file_path,
                "change_type": change.change_type,
                "new_content": change.new_content,
            }
            result = validate_patch(patch_dict)
            if not result.valid:
                all_errors.extend(
                    f"{change.file_path}: {e}" for e in result.errors
                )

            # Python syntax check for .py files
            if (
                change.file_path.endswith(".py")
                and change.change_type != "delete"
                and change.new_content
            ):
                syntax_result = validate_python_syntax(change.new_content)
                if not syntax_result.valid:
                    all_errors.extend(
                        f"{change.file_path}: {e}" for e in syntax_result.errors
                    )

        return (len(all_errors) == 0, all_errors)

    def _load_conventions(self) -> str:
        """Load a subset of CLAUDE.md for context."""
        claude_md = Path("CLAUDE.md")
        if not claude_md.exists():
            return "(CLAUDE.md not found)"
        content = claude_md.read_text(encoding="utf-8")
        # Truncate to keep prompt reasonable
        if len(content) > 3000:
            content = content[:3000] + "\n... (truncated)"
        return content

    async def _call_gemini(self, prompt: str) -> tuple[str, int]:
        """Call Gemini API and return (response_text, total_tokens)."""
        response = await self._client.aio.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
            ),
        )

        text = response.text or ""

        tokens = 0
        if response.usage_metadata:
            tokens = getattr(response.usage_metadata, "total_token_count", 0)
            if tokens == 0:
                tokens = (
                    (getattr(response.usage_metadata, "prompt_token_count", 0) or 0)
                    + (getattr(response.usage_metadata, "candidates_token_count", 0) or 0)
                )

        return text, tokens

    def _parse_response(self, text: str) -> GenerationResult:
        """Parse LLM response into GenerationResult."""
        try:
            cleaned = _extract_json(text)
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse LLM response: %s", exc)
            return GenerationResult(
                changes=[],
                summary=f"Parse error: {exc}",
                usage=self.usage,
            )

        summary = data.get("summary", "No summary provided")
        changes: list[CodeChange] = []
        for c in data.get("changes", []):
            changes.append(CodeChange(
                file_path=c.get("file_path", ""),
                change_type=c.get("change_type", "modify"),
                new_content=c.get("new_content"),
                description=c.get("description", ""),
            ))

        return GenerationResult(changes=changes, summary=summary, usage=self.usage)

    def get_relevant_files(
        self, failure_patterns: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Determine which source files are relevant to the failures and read them.

        Heuristic: map pattern_type → likely modules.
        """
        modules_map: dict[str, list[str]] = {
            "selector_not_found": [
                "src/core/llm_orchestrator.py",
                "src/ai/llm_planner.py",
                "src/core/extractor.py",
            ],
            "timeout": [
                "src/core/llm_orchestrator.py",
                "src/core/executor.py",
            ],
            "parse_error": [
                "src/ai/llm_planner.py",
                "src/ai/prompt_manager.py",
            ],
            "budget_exceeded": [
                "src/ai/llm_planner.py",
                "src/core/llm_orchestrator.py",
            ],
            "captcha": [
                "src/core/llm_orchestrator.py",
                "src/vision/vlm_client.py",
            ],
            "not_interactable": [
                "src/core/executor.py",
                "src/core/llm_orchestrator.py",
            ],
            "bot_detected": [
                "src/core/stealth.py",
                "src/core/human_behavior.py",
                "src/core/llm_orchestrator.py",
            ],
            "navigation_blocked": [
                "src/core/navigation.py",
                "src/core/executor.py",
            ],
        }

        needed: set[str] = set()
        for pattern in failure_patterns:
            ptype = pattern.get("pattern_type", "unknown")
            for mod in modules_map.get(ptype, []):
                needed.add(mod)

        # Always include orchestrator
        needed.add("src/core/llm_orchestrator.py")

        result: dict[str, str] = {}
        for fpath in sorted(needed):
            p = Path(fpath)
            if p.exists():
                content = p.read_text(encoding="utf-8")
                # Truncate large files
                if len(content) > 5000:
                    content = content[:5000] + "\n# ... (truncated)"
                result[fpath] = content

        return result


def _extract_json(text: str) -> str:
    """Extract JSON from LLM response (handles markdown fences)."""
    # Try markdown code fences
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()
    # Try raw JSON
    for ch in ("{", "["):
        if ch in text:
            idx = text.index(ch)
            return text[idx:].strip()
    return text.strip()
