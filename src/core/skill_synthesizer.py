"""SkillSynthesizer — convert successful trajectories to Python functions.

Unlike cache (stores selectors), Skills store Python code with multiple
fallback strategies. When selectors change, the logic in the function
can still work.

Three-stage security gate:
1. Syntax validation (ast.parse)
2. AST static analysis (forbidden nodes/calls, browser API whitelist)
3. Sandbox execution test (compile with restricted globals)
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
from typing import Any, Protocol

from src.core.types import Skill, V3StepResult

logger = logging.getLogger(__name__)

_SYNTHESIS_PROMPT_TEMPLATE = """\
아래는 웹 자동화 태스크의 성공한 실행 기록입니다.
이것을 재사용 가능한 async Python 함수로 변환하세요.

규칙:
- Browser 객체를 첫 번째 인자로 받을 것
- 셀렉터는 여러 대안을 or 체인으로 작성할 것 (사이트 변경 대비)
- 하드코딩된 값은 함수 파라미터로 빼낼 것
- 각 액션 후 간단한 성공 체크를 넣을 것
- import 문은 사용 금지 (Browser API만 사용 가능)
- 파일 시스템, 네트워크, OS 접근 금지

태스크: {task}
사이트: {domain}
실행 기록:
{trajectory}"""


class ISynthesizerLLM(Protocol):
    """LLM interface for skill synthesis."""

    async def generate(self, prompt: str) -> str: ...


class SkillSynthesizer:
    """Convert successful execution trajectories to Python functions.

    Usage:
        synth = SkillSynthesizer(llm=gemini_pro)
        skill = await synth.synthesize("검색", "naver.com", trajectory)
        if skill:
            is_valid = synth.validate(skill)
    """

    ALLOWED_BROWSER_METHODS = frozenset({
        "click_selector", "fill_selector", "mouse_click",
        "key_press", "type_text", "evaluate",
        "screenshot", "get_viewport_size", "wait", "url",
        "goto", "scroll",
    })

    FORBIDDEN_AST_NODES = frozenset({
        ast.Import, ast.ImportFrom,
        ast.Global, ast.Nonlocal,
    })

    FORBIDDEN_CALLS = frozenset({
        "exec", "eval", "compile", "__import__",
        "open", "os.", "sys.", "subprocess.",
        "shutil.", "pathlib.", "socket.",
    })

    def __init__(self, llm: ISynthesizerLLM) -> None:
        self._llm = llm

    async def synthesize(
        self,
        task: str,
        domain: str,
        trajectory: list[V3StepResult],
    ) -> Skill | None:
        """Synthesize a Skill from successful trajectory.

        Args:
            task: Task description.
            domain: Website domain.
            trajectory: List of successful step results.

        Returns:
            Skill if synthesis and validation succeed, None otherwise.
        """
        traj_text = self._format_trajectory(trajectory)
        prompt = _SYNTHESIS_PROMPT_TEMPLATE.format(
            task=task, domain=domain, trajectory=traj_text,
        )

        response = await self._llm.generate(prompt)
        code = self._extract_code(response)

        if not code:
            logger.warning("SkillSynthesizer: no code found in response")
            return None

        # Gate 1: Syntax validation
        if not self._validate_syntax(code):
            logger.warning("SkillSynthesizer: syntax error in generated code")
            return None

        # Gate 2: AST static analysis
        violations = self.ast_audit(code)
        if violations:
            logger.warning(
                "SkillSynthesizer: security violations: %s", violations,
            )
            return None

        name = self._generate_name(task, domain)
        return Skill(
            name=name,
            domain=domain,
            task_pattern=task,
            code=code,
        )

    def validate(self, skill: Skill) -> bool:
        """Validate a skill's code for syntax and security.

        Args:
            skill: The skill to validate.

        Returns:
            True if the skill passes all checks.
        """
        if not self._validate_syntax(skill.code):
            return False
        return len(self.ast_audit(skill.code)) == 0

    def ast_audit(self, code: str) -> list[str]:
        """Audit code via AST for security violations.

        Args:
            code: Python source code to audit.

        Returns:
            List of violation descriptions. Empty if clean.
        """
        violations: list[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ["SyntaxError"]

        for node in ast.walk(tree):
            # Check forbidden AST nodes
            if type(node) in self.FORBIDDEN_AST_NODES:
                violations.append(f"Forbidden node: {type(node).__name__}")

            # Check function calls
            if isinstance(node, ast.Call):
                call_name = self._get_call_name(node)
                if call_name and any(
                    call_name.startswith(f) for f in self.FORBIDDEN_CALLS
                ):
                    violations.append(f"Forbidden call: {call_name}")

            # Check browser method whitelist
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "browser"
                and node.attr not in self.ALLOWED_BROWSER_METHODS
            ):
                violations.append(
                    f"Disallowed browser API: {node.attr}"
                )

        return violations

    def compile_sandboxed(self, code: str) -> Any:
        """Compile skill code with restricted globals.

        Args:
            code: Python source code.

        Returns:
            The first async function defined in the code.

        Raises:
            ValueError: If no async function found.
        """
        allowed_globals: dict[str, Any] = {
            "__builtins__": {
                "len": len, "range": range, "str": str, "int": int,
                "float": float, "bool": bool, "list": list, "dict": dict,
                "tuple": tuple, "None": None, "True": True, "False": False,
                "print": print, "isinstance": isinstance,
                "enumerate": enumerate,
            },
            "asyncio": asyncio,
        }
        local_ns: dict[str, Any] = {}
        exec(code, allowed_globals, local_ns)  # noqa: S102

        for v in local_ns.values():
            if asyncio.iscoroutinefunction(v):
                return v

        raise ValueError("No async function found in skill code")

    def _validate_syntax(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def _get_call_name(self, node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            return f"{node.func.value.id}.{node.func.attr}"
        return None

    def _format_trajectory(self, trajectory: list[V3StepResult]) -> str:
        lines: list[str] = []
        for r in trajectory:
            step = r.step
            action = r.action
            lines.append(
                f"Step {step.step_index}: {step.action_type} "
                f"'{step.target_description}' "
                f"→ selector={action.selector}, "
                f"viewport_xy={action.viewport_xy}, "
                f"value={action.value}, "
                f"success={r.success}"
            )
        return "\n".join(lines)

    def _extract_code(self, response: str) -> str | None:
        """Extract Python code from LLM response."""
        # Try code fence
        fence_match = re.search(
            r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL,
        )
        if fence_match:
            return fence_match.group(1).strip()

        # Try to find async def
        async_match = re.search(
            r"(async def \w+.*)", response, re.DOTALL,
        )
        if async_match:
            return async_match.group(1).strip()

        return None

    def _generate_name(self, task: str, domain: str) -> str:
        """Generate a function name from task and domain."""
        # Simplify domain
        domain_part = domain.replace(".", "_").replace("-", "_")
        # Simplify task (take first few words)
        task_words = re.findall(r"[a-zA-Z가-힣]+", task)[:3]
        task_part = "_".join(task_words) if task_words else "skill"
        return f"{domain_part}_{task_part}"
