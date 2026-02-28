"""Tests for SkillSynthesizer — trajectory → Python function conversion."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.skill_synthesizer import SkillSynthesizer
from src.core.types import Action, StepPlan, V3StepResult


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=(
            "```python\n"
            "async def search(browser, query):\n"
            "    await browser.click_selector('#search')\n"
            "    await browser.fill_selector('#search', query)\n"
            "```"
        )
    )
    return llm


@pytest.fixture
def synth(mock_llm: AsyncMock) -> SkillSynthesizer:
    return SkillSynthesizer(llm=mock_llm)


@pytest.fixture
def trajectory() -> list[V3StepResult]:
    step0 = StepPlan(
        step_index=0, action_type="click",
        target_description="검색창 클릭",
        keyword_weights={"검색": 0.9},
        target_viewport_xy=(0.5, 0.03),
    )
    action0 = Action(
        selector="#search-input", action_type="click",
        viewport_xy=(0.5, 0.03),
    )
    step1 = StepPlan(
        step_index=1, action_type="type",
        target_description="검색어 입력", value="등산복",
        keyword_weights={"검색": 0.9},
        target_viewport_xy=(0.5, 0.03),
    )
    action1 = Action(
        selector="#search-input", action_type="type",
        value="등산복", viewport_xy=(0.5, 0.03),
    )
    return [
        V3StepResult(step=step0, action=action0, success=True,
                     pre_url="https://example.com",
                     post_url="https://example.com"),
        V3StepResult(step=step1, action=action1, success=True,
                     pre_url="https://example.com",
                     post_url="https://example.com/search?q=등산복"),
    ]


# ── Synthesis ──


class TestSynthesize:
    async def test_basic_synthesis(
        self, synth: SkillSynthesizer, trajectory: list[V3StepResult],
    ) -> None:
        skill = await synth.synthesize("검색", "naver.com", trajectory)
        assert skill is not None
        assert skill.domain == "naver.com"
        assert "async def" in skill.code

    async def test_returns_none_on_no_code(
        self, synth: SkillSynthesizer, mock_llm: AsyncMock,
        trajectory: list[V3StepResult],
    ) -> None:
        mock_llm.generate = AsyncMock(
            return_value="I don't know how to do that."
        )
        skill = await synth.synthesize("task", "example.com", trajectory)
        assert skill is None

    async def test_returns_none_on_syntax_error(
        self, synth: SkillSynthesizer, mock_llm: AsyncMock,
        trajectory: list[V3StepResult],
    ) -> None:
        mock_llm.generate = AsyncMock(
            return_value="```python\ndef foo(\n```"
        )
        skill = await synth.synthesize("task", "example.com", trajectory)
        assert skill is None

    async def test_returns_none_on_security_violation(
        self, synth: SkillSynthesizer, mock_llm: AsyncMock,
        trajectory: list[V3StepResult],
    ) -> None:
        mock_llm.generate = AsyncMock(
            return_value=(
                "```python\n"
                "import os\n"
                "async def hack(browser):\n"
                "    os.system('rm -rf /')\n"
                "```"
            )
        )
        skill = await synth.synthesize("task", "example.com", trajectory)
        assert skill is None

    async def test_name_generation(
        self, synth: SkillSynthesizer, trajectory: list[V3StepResult],
    ) -> None:
        skill = await synth.synthesize("검색 실행", "shop.naver.com", trajectory)
        assert skill is not None
        assert "shop_naver_com" in skill.name
        assert "검색" in skill.name


# ── AST Audit ──


class TestAstAudit:
    def test_clean_code(self, synth: SkillSynthesizer) -> None:
        code = (
            "async def search(browser):\n"
            "    await browser.click_selector('#btn')\n"
        )
        assert synth.ast_audit(code) == []

    def test_import_forbidden(self, synth: SkillSynthesizer) -> None:
        code = "import os\nasync def f(browser): pass\n"
        violations = synth.ast_audit(code)
        assert any("Import" in v for v in violations)

    def test_import_from_forbidden(self, synth: SkillSynthesizer) -> None:
        code = "from os import path\nasync def f(browser): pass\n"
        violations = synth.ast_audit(code)
        assert any("ImportFrom" in v for v in violations)

    def test_exec_forbidden(self, synth: SkillSynthesizer) -> None:
        code = (
            "async def f(browser):\n"
            "    exec('print(1)')\n"
        )
        violations = synth.ast_audit(code)
        assert any("exec" in v for v in violations)

    def test_eval_forbidden(self, synth: SkillSynthesizer) -> None:
        code = (
            "async def f(browser):\n"
            "    eval('1+1')\n"
        )
        violations = synth.ast_audit(code)
        assert any("eval" in v for v in violations)

    def test_open_forbidden(self, synth: SkillSynthesizer) -> None:
        code = (
            "async def f(browser):\n"
            "    open('/etc/passwd')\n"
        )
        violations = synth.ast_audit(code)
        assert any("open" in v for v in violations)

    def test_os_call_forbidden(self, synth: SkillSynthesizer) -> None:
        code = (
            "async def f(browser):\n"
            "    os.system('ls')\n"
        )
        violations = synth.ast_audit(code)
        assert any("os." in v for v in violations)

    def test_subprocess_forbidden(self, synth: SkillSynthesizer) -> None:
        code = (
            "async def f(browser):\n"
            "    subprocess.run(['ls'])\n"
        )
        violations = synth.ast_audit(code)
        assert any("subprocess." in v for v in violations)

    def test_disallowed_browser_method(
        self, synth: SkillSynthesizer,
    ) -> None:
        code = (
            "async def f(browser):\n"
            "    await browser.execute_script('evil')\n"
        )
        violations = synth.ast_audit(code)
        assert any("execute_script" in v for v in violations)

    def test_allowed_browser_methods(
        self, synth: SkillSynthesizer,
    ) -> None:
        code = (
            "async def f(browser):\n"
            "    await browser.click_selector('#btn')\n"
            "    await browser.fill_selector('#input', 'text')\n"
            "    await browser.screenshot()\n"
            "    await browser.goto('https://example.com')\n"
        )
        assert synth.ast_audit(code) == []

    def test_syntax_error_returns_violation(
        self, synth: SkillSynthesizer,
    ) -> None:
        violations = synth.ast_audit("def foo(")
        assert violations == ["SyntaxError"]

    def test_global_forbidden(self, synth: SkillSynthesizer) -> None:
        code = (
            "x = 1\n"
            "async def f(browser):\n"
            "    global x\n"
            "    x = 2\n"
        )
        violations = synth.ast_audit(code)
        assert any("Global" in v for v in violations)


# ── Compile Sandboxed ──


class TestCompileSandboxed:
    def test_returns_async_function(
        self, synth: SkillSynthesizer,
    ) -> None:
        code = (
            "async def my_skill(browser):\n"
            "    await browser.click_selector('#btn')\n"
        )
        fn = synth.compile_sandboxed(code)
        import asyncio
        assert asyncio.iscoroutinefunction(fn)
        assert fn.__name__ == "my_skill"

    def test_no_async_function_raises(
        self, synth: SkillSynthesizer,
    ) -> None:
        code = "def sync_func(): pass\n"
        with pytest.raises(ValueError, match="No async function"):
            synth.compile_sandboxed(code)

    def test_restricted_builtins(
        self, synth: SkillSynthesizer,
    ) -> None:
        code = (
            "async def f(browser):\n"
            "    return len([1, 2, 3])\n"
        )
        fn = synth.compile_sandboxed(code)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(fn(None))
        assert result == 3


# ── Code Extraction ──


class TestExtractCode:
    def test_extracts_from_code_fence(
        self, synth: SkillSynthesizer,
    ) -> None:
        response = (
            "Here's the code:\n"
            "```python\n"
            "async def search(browser):\n"
            "    pass\n"
            "```\n"
            "That's it."
        )
        code = synth._extract_code(response)
        assert code is not None
        assert "async def search" in code

    def test_extracts_from_bare_fence(
        self, synth: SkillSynthesizer,
    ) -> None:
        response = (
            "```\n"
            "async def search(browser):\n"
            "    pass\n"
            "```"
        )
        code = synth._extract_code(response)
        assert code is not None
        assert "async def search" in code

    def test_extracts_raw_async_def(
        self, synth: SkillSynthesizer,
    ) -> None:
        response = (
            "Sure, here you go:\n"
            "async def search(browser):\n"
            "    await browser.click_selector('#btn')\n"
        )
        code = synth._extract_code(response)
        assert code is not None
        assert "async def search" in code

    def test_returns_none_for_no_code(
        self, synth: SkillSynthesizer,
    ) -> None:
        assert synth._extract_code("No code here") is None

    def test_returns_none_for_empty_response(
        self, synth: SkillSynthesizer,
    ) -> None:
        assert synth._extract_code("") is None


# ── Validate ──


class TestValidate:
    def test_valid_skill(self, synth: SkillSynthesizer) -> None:
        from src.core.types import Skill
        skill = Skill(
            name="test", domain="example.com",
            task_pattern="검색",
            code=(
                "async def search(browser):\n"
                "    await browser.click_selector('#btn')\n"
            ),
        )
        assert synth.validate(skill) is True

    def test_invalid_skill_syntax(
        self, synth: SkillSynthesizer,
    ) -> None:
        from src.core.types import Skill
        skill = Skill(
            name="test", domain="example.com",
            task_pattern="검색", code="def foo(",
        )
        assert synth.validate(skill) is False

    def test_invalid_skill_security(
        self, synth: SkillSynthesizer,
    ) -> None:
        from src.core.types import Skill
        skill = Skill(
            name="test", domain="example.com",
            task_pattern="검색",
            code="import os\nasync def f(b): pass\n",
        )
        assert synth.validate(skill) is False


# ── Name Generation ──


class TestGenerateName:
    def test_basic_name(self, synth: SkillSynthesizer) -> None:
        name = synth._generate_name("검색 실행", "naver.com")
        assert "naver_com" in name
        assert "검색" in name

    def test_complex_domain(self, synth: SkillSynthesizer) -> None:
        name = synth._generate_name("task", "search.shopping.naver.com")
        assert "search_shopping_naver_com" in name

    def test_empty_task(self, synth: SkillSynthesizer) -> None:
        name = synth._generate_name("", "example.com")
        assert "skill" in name


# ── Format Trajectory ──


class TestFormatTrajectory:
    def test_formats_trajectory(
        self, synth: SkillSynthesizer, trajectory: list[V3StepResult],
    ) -> None:
        text = synth._format_trajectory(trajectory)
        assert "Step 0" in text
        assert "Step 1" in text
        assert "click" in text
        assert "type" in text
        assert "#search-input" in text

    def test_empty_trajectory(self, synth: SkillSynthesizer) -> None:
        assert synth._format_trajectory([]) == ""
