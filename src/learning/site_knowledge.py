"""SiteKnowledgeStore — JSON-based per-domain site knowledge.

Stores site-specific structural knowledge as JSON files, one per domain.
LLM (Flash) merges new run results with existing knowledge:
  - Deduplicates successful paths
  - Preserves failed approaches so the same mistakes aren't repeated
  - Extracts reusable tips

Loaded into Planner prompts via render_knowledge() for informed planning.

Usage:
    store = SiteKnowledgeStore(base_dir=Path("data/site_knowledge"))
    # Read rendered knowledge for planner prompt
    knowledge_md = store.load("danawa.com")
    # Save run results with LLM merge
    await store.save_run("danawa.com", completed, failed, task, llm)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path("data/site_knowledge")
_DEFAULT_MAX_CHARS = 2000
_MAX_ENTRIES = 5
_RENDER_MAX_CHARS = 800
_SCHEMA_VERSION = 1


def extract_domain(url: str) -> str:
    """Extract domain from URL, stripping www. prefix."""
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _safe_filename(domain: str) -> str:
    """Sanitize domain into a safe filename."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", domain)


def _empty_knowledge(domain: str) -> dict[str, Any]:
    """Create empty JSON knowledge structure."""
    return {
        "domain": domain,
        "version": _SCHEMA_VERSION,
        "successful_paths": [],
        "failed_approaches": [],
        "tips": [],
    }


def _now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(UTC).isoformat()


class ITextLLM(Protocol):
    """Minimal text LLM interface for knowledge merge."""

    async def generate(self, prompt: str) -> str: ...


def _extract_json_from_response(text: str) -> dict[str, Any] | None:
    """Extract JSON object from LLM response (code fence or raw)."""
    # Try code fence first
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

    # Try raw JSON
    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

    return None


def _deterministic_merge(
    existing: dict[str, Any],
    completed_steps: list[Any],
    failed_steps: list[tuple[Any, str]],
    task: str,
) -> dict[str, Any]:
    """Merge without LLM — simple dedup and append.

    Used as fallback when LLM is unavailable or fails.
    """
    data: dict[str, Any] = json.loads(json.dumps(existing))  # deep copy
    now = _now_iso()

    # Build step descriptions
    step_descs = []
    for s in completed_steps:
        tag = f"[{s.action_type}]" if hasattr(s, "action_type") and s.action_type else ""
        step_descs.append(f"{tag} {s.target_description}".strip())

    # Add successful path if we have completed steps
    if step_descs:
        # Check for duplicate task (same task name)
        existing_tasks = {
            p["task"] for p in data.get("successful_paths", [])
        }
        if task not in existing_tasks:
            data["successful_paths"].append({
                "task": task,
                "steps": step_descs,
                "last_success": now,
            })
        else:
            # Update existing entry's timestamp and steps
            for p in data["successful_paths"]:
                if p["task"] == task:
                    p["steps"] = step_descs
                    p["last_success"] = now
                    break

    # Add failed approaches
    for step_plan, reason in failed_steps:
        if hasattr(step_plan, "action_type"):
            desc = f"[{step_plan.action_type}] {step_plan.target_description}".strip()
        else:
            desc = str(step_plan)
        # Check for duplicate
        existing_descs = {
            f["step"] for f in data.get("failed_approaches", [])
        }
        if desc not in existing_descs:
            # Auto-suggest hover for menu/category click failures
            alt = ""
            action_type = getattr(step_plan, "action_type", "")
            target = getattr(step_plan, "target_description", "")
            _menu_kw = ("메뉴", "카테고리", "category", "menu", "nav")
            if action_type == "click" and any(
                k in target.lower() for k in _menu_kw
            ):
                alt = "hover로 메뉴를 먼저 열고 하위 항목 탐색"
            data["failed_approaches"].append({
                "step": desc,
                "reason": reason,
                "alternative": alt,
                "failed_at": now,
            })

    # Trim to max entries
    data["successful_paths"] = data["successful_paths"][-_MAX_ENTRIES:]
    data["failed_approaches"] = data["failed_approaches"][-_MAX_ENTRIES:]
    data["tips"] = data.get("tips", [])[-_MAX_ENTRIES:]

    return data


async def merge_knowledge(
    existing: dict[str, Any],
    completed_steps: list[Any],
    failed_steps: list[tuple[Any, str]],
    task: str,
    llm: ITextLLM | None,
) -> dict[str, Any]:
    """Merge new run results into existing knowledge using LLM.

    Falls back to deterministic merge if LLM is None or fails.
    """
    if llm is None:
        return _deterministic_merge(existing, completed_steps, failed_steps, task)

    # Build step descriptions for prompt
    completed_descs = []
    for s in completed_steps:
        tag = f"[{s.action_type}]" if hasattr(s, "action_type") and s.action_type else ""
        completed_descs.append(f"{tag} {s.target_description}".strip())

    failed_descs = []
    for step_plan, reason in failed_steps:
        if hasattr(step_plan, "action_type"):
            desc = f"[{step_plan.action_type}] {step_plan.target_description}".strip()
        else:
            desc = str(step_plan)
        failed_descs.append(f"{desc} (사유: {reason})")

    prompt = f"""기존 사이트 지식(JSON)과 새 실행 결과를 병합하세요.

기존 지식:
```json
{json.dumps(existing, ensure_ascii=False, indent=2)}
```

이번 실행:
- 태스크: {task}
- 성공 스텝: {json.dumps(completed_descs, ensure_ascii=False)}
- 실패 스텝: {json.dumps(failed_descs, ensure_ascii=False)}

병합 규칙:
1. successful_paths: 새 성공 추가, 같은 task는 업데이트, 최대 {_MAX_ENTRIES}개 (오래된 것 먼저 삭제)
2. failed_approaches: "step" 키 필수(action 금지). reason+alternative, 최대 {_MAX_ENTRIES}개
3. tips: 일반화 가능한 팁 추출, 기존과 중복 제거, 최대 {_MAX_ENTRIES}개
4. 기존 successful_paths가 이번에 실패했으면 → 해당 경로 삭제 → failed_approaches로 이동
5. 카테고리 메뉴 클릭 실패 → alternative에 "hover로 메뉴 열기" 포함
6. visual_filter는 사이트 UI 필터보다 항상 우선.
   "사이트 필터가 visual_filter보다 정확/빠르다" 같은 팁 절대 금지

JSON만 출력하세요:
```json
{{
  "domain": "{existing.get('domain', '')}",
  "version": 1,
  "successful_paths": [...],
  "failed_approaches": [...],
  "tips": [...]
}}
```"""

    try:
        response = await llm.generate(prompt)
        parsed = _extract_json_from_response(response)
        if parsed and "successful_paths" in parsed:
            # Normalize: "action" → "step" in failed_approaches
            for fa in parsed.get("failed_approaches", []):
                if "action" in fa and "step" not in fa:
                    fa["step"] = fa.pop("action")
            # Enforce entry limits
            parsed["successful_paths"] = parsed.get("successful_paths", [])[:_MAX_ENTRIES]
            parsed["failed_approaches"] = parsed.get("failed_approaches", [])[:_MAX_ENTRIES]
            parsed["tips"] = parsed.get("tips", [])[:_MAX_ENTRIES]
            parsed["domain"] = existing.get("domain", "")
            parsed["version"] = _SCHEMA_VERSION
            return parsed
    except Exception:
        logger.warning("LLM merge failed, using deterministic fallback")

    return _deterministic_merge(existing, completed_steps, failed_steps, task)


def render_knowledge(
    data: dict[str, Any],
    max_chars: int = _RENDER_MAX_CHARS,
) -> str:
    """Render JSON knowledge as compact markdown for planner prompt.

    Priority order: failed approaches > successful paths > tips.
    Truncates to max_chars.
    """
    if not data:
        return ""

    has_failed = bool(data.get("failed_approaches"))
    has_success = bool(data.get("successful_paths"))
    has_tips = bool(data.get("tips"))

    if not has_failed and not has_success and not has_tips:
        return ""

    parts: list[str] = []

    # 1. Failed approaches (most important — prevent repeating mistakes)
    if has_failed:
        lines = ["## 실패 (반복 금지)"]
        for f in data["failed_approaches"][:3]:
            step = f.get("step", "") or f.get("action", "")
            reason = f.get("reason", "")
            alt = f.get("alternative", "")
            line = f"- {step}"
            if reason:
                line += f" → {reason}"
            if alt:
                line += f" (대신: {alt})"
            lines.append(line)
        parts.append("\n".join(lines))

    # 2. Successful paths
    if has_success:
        lines = ["## 성공 경로"]
        for p in data["successful_paths"][:2]:
            task_name = p.get("task", "")
            steps = p.get("steps", [])
            lines.append(f"- {task_name}: {' → '.join(steps)}")
        parts.append("\n".join(lines))

    # 3. Tips
    if has_tips:
        lines = ["## 팁"]
        for t in data["tips"][:3]:
            tip_text = t if isinstance(t, str) else str(t)
            lines.append(f"- {tip_text}")
        parts.append("\n".join(lines))

    result = "\n\n".join(parts)
    if len(result) > max_chars:
        result = result[:max_chars]
    return result


class SiteKnowledgeStore:
    """Load and save per-domain site knowledge as JSON files.

    Backward-compatible: load() returns rendered markdown string.
    New: load_raw() returns parsed JSON dict.
    New: save_run() merges with LLM and saves JSON.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or _DEFAULT_DIR

    def _json_path(self, domain: str) -> Path:
        safe = _safe_filename(domain)
        return self._base_dir / f"{safe}.json"

    def _md_path(self, domain: str) -> Path:
        """Legacy .md path for backward compat."""
        safe = _safe_filename(domain)
        return self._base_dir / f"{safe}.md"

    def load_raw(self, domain: str) -> dict[str, Any]:
        """Load raw JSON knowledge for a domain. Returns empty structure if none."""
        path = self._json_path(domain)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data  # type: ignore[no-any-return]
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to read site knowledge JSON: %s", path)

        # Fallback: try legacy .md file → return empty (don't parse MD)
        return _empty_knowledge(domain)

    def load(self, domain: str) -> str:
        """Load site knowledge as rendered markdown. Returns empty string if none."""
        data = self.load_raw(domain)
        return render_knowledge(data)

    def save(
        self,
        domain: str,
        content: str,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ) -> None:
        """Legacy save — writes raw markdown content. Kept for backward compat."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        if len(content) > max_chars:
            content = content[:max_chars]
        path = self._md_path(domain)
        path.write_text(content, encoding="utf-8")
        logger.info("Saved site knowledge (legacy MD): %s (%d chars)", domain, len(content))

    def _save_json(self, domain: str, data: dict[str, Any]) -> None:
        """Save JSON knowledge with entry limits enforced."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        # Enforce limits
        data["successful_paths"] = data.get("successful_paths", [])[-_MAX_ENTRIES:]
        data["failed_approaches"] = data.get("failed_approaches", [])[-_MAX_ENTRIES:]
        data["tips"] = data.get("tips", [])[-_MAX_ENTRIES:]

        path = self._json_path(domain)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved site knowledge JSON: %s", domain)

    async def save_run(
        self,
        domain: str,
        completed_steps: list[Any],
        failed_steps: list[tuple[Any, str]],
        task: str,
        llm: ITextLLM | None = None,
    ) -> None:
        """Merge new run results with existing knowledge and save.

        Uses LLM for intelligent merge when available, falls back to
        deterministic dedup otherwise.
        """
        existing = self.load_raw(domain)
        merged = await merge_knowledge(
            existing, completed_steps, failed_steps, task, llm,
        )
        self._save_json(domain, merged)
