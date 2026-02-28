"""R(Rule Engine) — YAML DSL rule matching with synonym-based heuristics.

Token cost: 0 (pure rule-based, no LLM calls).

The rule engine loads rules from ``config/rules/*.yaml`` and a synonym
dictionary from ``config/synonyms.yaml`` at initialisation.  It provides:

* **match** — deterministic intent-to-rule matching (site pattern + synonym).
* **heuristic_select** — score candidates by text similarity, role, and position
  to pick the best element *without* any LLM invocation.
* **register_rule** — dynamically add a promoted rule (P5 learning loop).
"""
from __future__ import annotations

import fnmatch
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from src.core.types import (
    ExtractedElement,
    PageState,
    RuleDefinition,
    RuleMatch,
)

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────
_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_RULES_GLOB = "rules/*.yaml"
_SYNONYMS_FILE = "synonyms.yaml"

# Rule categories recognised by the engine.
VALID_CATEGORIES = frozenset(
    {"popup", "search", "sort", "filter", "pagination", "login", "error"}
)

# ── Helpers ──────────────────────────────────────────


def _normalise(text: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _text_similarity(a: str, b: str) -> float:
    """Return 0.0-1.0 SequenceMatcher ratio between two normalised strings."""
    return SequenceMatcher(None, _normalise(a), _normalise(b)).ratio()


def _role_score(element: ExtractedElement, method: str) -> float:
    """Score bonus when ARIA role matches the expected interaction method.

    Non-visible elements receive zero role score since they cannot be
    meaningfully interacted with.

    Args:
        element: Candidate element.
        method: Expected interaction method (click, type, etc.).

    Returns:
        Score between 0.0 and 0.3.
    """
    if not element.visible:
        return 0.0

    role = (element.role or "").lower()
    etype = element.type.lower()

    click_roles = {"button", "link", "tab", "menuitem", "option"}
    type_roles = {"textbox", "searchbox", "input", "combobox"}

    if method == "click" and (role in click_roles or etype in {"button", "link", "tab"}):
        return 0.3
    if method == "type" and (role in type_roles or etype in {"input"}):
        return 0.3
    if role or etype:
        return 0.1
    return 0.0


def _position_score(element: ExtractedElement) -> float:
    """Favour elements higher on the page (smaller y) and visible.

    Returns:
        Score between 0.0 and 0.2.
    """
    if not element.visible:
        return 0.0
    _, y, _, _ = element.bbox
    # Favour elements in the top 600px of the viewport.
    if y <= 0:
        return 0.15
    if y < 300:
        return 0.2
    if y < 600:
        return 0.15
    return 0.05


# ── RuleEngine ───────────────────────────────────────


class RuleEngine:
    """YAML DSL rule engine implementing ``IRuleEngine`` Protocol.

    Args:
        config_dir: Root config directory containing ``synonyms.yaml``
            and ``rules/`` sub-directory.  Defaults to ``<project>/config``.

    Example::

        engine = RuleEngine()
        match = engine.match("인기순 정렬", page_state)
        if match:
            await executor.click(match.selector)
    """

    def __init__(self, config_dir: Path | str | None = None) -> None:
        self._config_dir = Path(config_dir) if config_dir else _DEFAULT_CONFIG_DIR
        self._rules: list[RuleDefinition] = []
        self._synonyms: dict[str, dict[str, list[str]]] = {}
        self._flat_synonyms: dict[str, str] = {}  # term -> canonical key

        self._load_synonyms()
        self._load_rules()

    # ── Public API (IRuleEngine Protocol) ────────────

    def match(self, intent: str, context: PageState) -> RuleMatch | None:
        """Match *intent* against loaded rules, considering site pattern.

        Args:
            intent: Natural-language intent string (e.g. "인기순 정렬").
            context: Current page state (used for URL-based site matching).

        Returns:
            A ``RuleMatch`` if a rule fires, otherwise ``None``.
        """
        norm_intent = _normalise(intent)
        # Resolve canonical key for any synonym present in the intent.
        resolved_keys = self._resolve_synonym_keys(norm_intent)

        # Iterate rules in priority order (highest first).
        for rule in self._rules_by_priority():
            # Site pattern check.
            if not self._site_matches(rule.site_pattern, context.url):
                continue

            # Intent matching: check direct pattern match + synonym overlap.
            norm_pattern = _normalise(rule.intent_pattern)
            if self._intent_matches(norm_intent, norm_pattern, resolved_keys, rule):
                return RuleMatch(
                    rule_id=rule.rule_id,
                    selector=rule.selector,
                    method=rule.method,
                    arguments=list(rule.arguments),
                    confidence=1.0,
                )

        return None

    def heuristic_select(
        self, candidates: list[ExtractedElement], intent: str
    ) -> str | None:
        """Score candidates and return the ``eid`` of the best match.

        Scoring factors:
        * Text similarity to the intent (weight 0.5)
        * Role compatibility (weight 0.3)
        * Page position (weight 0.2)

        Args:
            candidates: Elements extracted from the page.
            intent: The intent describing what to interact with.

        Returns:
            ``eid`` of the best candidate, or ``None`` if no viable match.
        """
        if not candidates:
            return None

        norm_intent = _normalise(intent)
        # Also expand the intent through synonyms.
        expanded_terms = self._expand_intent_terms(norm_intent)

        best_eid: str | None = None
        best_score: float = -1.0

        for elem in candidates:
            # Text similarity — compare against element text AND parent context.
            text_sim = 0.0
            if elem.text:
                direct_sim = _text_similarity(elem.text, norm_intent)
                # Also check synonym-expanded terms.
                syn_sim = max(
                    (_text_similarity(elem.text, t) for t in expanded_terms),
                    default=0.0,
                )
                text_sim = max(direct_sim, syn_sim)
            if elem.parent_context:
                ctx_sim = _text_similarity(elem.parent_context, norm_intent)
                text_sim = max(text_sim, ctx_sim * 0.8)

            # Determine expected method from intent keywords.
            method_hint = self._guess_method(norm_intent)

            role = _role_score(elem, method_hint)
            pos = _position_score(elem)

            score = text_sim * 0.5 + role * 0.3 + pos * 0.2

            if score > best_score:
                best_score = score
                best_eid = elem.eid

        # Require a minimum confidence threshold.
        if best_score < 0.15:
            return None

        return best_eid

    def register_rule(self, rule: RuleDefinition) -> None:
        """Dynamically add a rule (e.g. promoted from learning loop).

        Args:
            rule: The rule definition to register.

        Raises:
            ValueError: If the rule category is not recognised.
        """
        if rule.category not in VALID_CATEGORIES:
            raise ValueError(
                f"Unknown rule category '{rule.category}'. "
                f"Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
            )
        # Avoid duplicate rule_ids.
        existing_ids = {r.rule_id for r in self._rules}
        if rule.rule_id in existing_ids:
            # Replace existing rule with updated version.
            self._rules = [r for r in self._rules if r.rule_id != rule.rule_id]

        self._rules.append(rule)
        logger.info("Registered rule: %s (priority=%d)", rule.rule_id, rule.priority)

    # ── Accessors ────────────────────────────────────

    @property
    def rules(self) -> list[RuleDefinition]:
        """Return a copy of all loaded rules."""
        return list(self._rules)

    @property
    def synonyms(self) -> dict[str, dict[str, list[str]]]:
        """Return the loaded synonym dictionary."""
        return dict(self._synonyms)

    # ── Private Helpers ──────────────────────────────

    def _load_synonyms(self) -> None:
        """Load synonym dictionary from ``config/synonyms.yaml``."""
        path = self._config_dir / _SYNONYMS_FILE
        if not path.exists():
            logger.warning("Synonyms file not found: %s", path)
            return

        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        self._synonyms = {}
        self._flat_synonyms = {}

        for group_name, group_dict in data.items():
            if not isinstance(group_dict, dict):
                continue
            self._synonyms[group_name] = {}
            for canonical, terms in group_dict.items():
                term_list = terms if isinstance(terms, list) else [terms]
                self._synonyms[group_name][canonical] = term_list
                # Build flat lookup: each term -> "group.canonical"
                qualified = f"{group_name}.{canonical}"
                for term in term_list:
                    self._flat_synonyms[_normalise(str(term))] = qualified
                # Also map the canonical name itself.
                self._flat_synonyms[_normalise(canonical)] = qualified

        logger.debug(
            "Loaded %d synonym groups with %d total terms",
            len(self._synonyms),
            len(self._flat_synonyms),
        )

    def _load_rules(self) -> None:
        """Load all rule YAML files from ``config/rules/``."""
        rules_dir = self._config_dir / "rules"
        if not rules_dir.is_dir():
            logger.warning("Rules directory not found: %s", rules_dir)
            return

        for path in sorted(rules_dir.glob("*.yaml")):
            try:
                self._parse_rule_file(path)
            except Exception:
                logger.exception("Failed to load rule file: %s", path)

        logger.debug("Loaded %d rules from %s", len(self._rules), rules_dir)

    def _parse_rule_file(self, path: Path) -> None:
        """Parse a rule YAML file and append rules to ``self._rules``.

        Supports two formats:

        1. **Single rule** — top-level ``rule:`` key with one rule dict.
        2. **Multiple rules** — top-level ``rules:`` key with a list of rule dicts.

        The YAML structure is flexible — we extract the fields needed to
        build a ``RuleDefinition``.  Fields that are absent get defaults.
        """
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        # Support multiple rules via top-level ``rules:`` list.
        rules_list = data.get("rules")
        if isinstance(rules_list, list):
            for rule_data in rules_list:
                if isinstance(rule_data, dict):
                    self._parse_single_rule(rule_data, path)
            return

        # Single rule via ``rule:`` key or flat structure.
        rule_data = data.get("rule", data)
        self._parse_single_rule(rule_data, path)

    def _parse_single_rule(self, rule_data: dict[str, Any], path: Path) -> None:
        """Parse a single rule dict and append to ``self._rules``.

        Args:
            rule_data: Dictionary with rule fields.
            path: Source file path (used as fallback for rule_id).
        """
        rule_id = rule_data.get("name", path.stem)
        trigger = rule_data.get("trigger", {})
        guardrail = rule_data.get("guardrail", {})

        # Derive category from the rule name or a dedicated field.
        category = rule_data.get("category", self._infer_category(rule_id))

        intent_pattern = trigger.get("intent", rule_data.get("intent", rule_id))
        site_pattern = trigger.get("site_pattern", rule_data.get("site_pattern", "*"))
        selector = rule_data.get("selector", "")
        method = rule_data.get("method", "click")
        arguments: list[str] = rule_data.get("arguments", [])
        priority = rule_data.get("priority", guardrail.get("priority", 0))

        self._rules.append(
            RuleDefinition(
                rule_id=rule_id,
                category=category,
                intent_pattern=intent_pattern,
                selector=selector,
                method=method,
                arguments=arguments,
                site_pattern=site_pattern,
                priority=priority,
            )
        )

    @staticmethod
    def _infer_category(rule_id: str) -> str:
        """Infer rule category from rule_id prefix."""
        for cat in VALID_CATEGORIES:
            if cat in rule_id.lower():
                return cat
        return "search"  # default

    def _rules_by_priority(self) -> list[RuleDefinition]:
        """Return rules sorted by priority descending."""
        return sorted(self._rules, key=lambda r: r.priority, reverse=True)

    def _site_matches(self, pattern: str, url: str) -> bool:
        """Check if *url* matches the glob *pattern*.

        Args:
            pattern: Glob pattern like ``*.naver.com`` or ``*``.
            url: Full URL from page state.

        Returns:
            True if matching.
        """
        if pattern == "*":
            return True
        # Extract hostname from URL.
        try:
            # Simple hostname extraction — avoids urllib for speed.
            host = url.split("//", 1)[-1].split("/", 1)[0].split(":")[0]
        except (IndexError, AttributeError):
            return False
        return fnmatch.fnmatch(host, pattern)

    def _resolve_synonym_keys(self, norm_intent: str) -> set[str]:
        """Find all canonical synonym keys that appear in the intent."""
        keys: set[str] = set()
        for term, qualified_key in self._flat_synonyms.items():
            if term in norm_intent:
                keys.add(qualified_key)
        return keys

    def _intent_matches(
        self,
        norm_intent: str,
        norm_pattern: str,
        resolved_keys: set[str],
        rule: RuleDefinition,
    ) -> bool:
        """Determine whether an intent matches a rule.

        Matching criteria (any is sufficient):
        1. Direct substring match (pattern in intent or intent in pattern).
        2. High text similarity (>= 0.6).
        3. Synonym overlap — rule references a synonym group that the intent resolves to.
        """
        # 1. Substring.
        if norm_pattern in norm_intent or norm_intent in norm_pattern:
            return True

        # 2. Similarity.
        if _text_similarity(norm_intent, norm_pattern) >= 0.6:
            return True

        # 3. Synonym overlap: check if any resolved key from the intent
        #    matches the rule_id naming convention or the rule's intent pattern
        #    resolves to the same synonym group.
        rule_resolved = self._resolve_synonym_keys(norm_pattern)
        if resolved_keys and rule_resolved and resolved_keys & rule_resolved:
            return True

        # Also check if any synonym term from the rule's intent pattern
        # appears directly in the user intent.
        pattern_terms = set(norm_pattern.split())
        intent_terms = set(norm_intent.split())
        return bool(pattern_terms & intent_terms)

    def _expand_intent_terms(self, norm_intent: str) -> list[str]:
        """Expand intent into additional synonym terms for heuristic matching."""
        terms: list[str] = [norm_intent]
        resolved_keys = self._resolve_synonym_keys(norm_intent)

        for qualified_key in resolved_keys:
            parts = qualified_key.split(".", 1)
            if len(parts) == 2:
                group, canonical = parts
                group_dict = self._synonyms.get(group, {})
                syn_list = group_dict.get(canonical, [])
                for syn in syn_list:
                    terms.append(_normalise(str(syn)))

        return terms

    @staticmethod
    def _guess_method(norm_intent: str) -> str:
        """Guess interaction method from intent keywords."""
        type_keywords = {"입력", "타이핑", "검색어", "type", "input", "enter", "write"}
        for kw in type_keywords:
            if kw in norm_intent:
                return "type"
        return "click"
