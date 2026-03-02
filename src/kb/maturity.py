"""Maturity tracking per domain — persisted in KB."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.models.maturity import MaturityState

logger = logging.getLogger(__name__)


class MaturityTracker:
    """Load/save/update maturity state per domain."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    def _path(self, domain: str) -> Path:
        return self._base / domain / "maturity.json"

    def load(self, domain: str) -> MaturityState:
        """Load maturity state for a domain. Returns cold state if missing."""
        p = self._path(domain)
        if not p.exists():
            return MaturityState(domain=domain)
        try:
            data = json.loads(p.read_text())
            return MaturityState(**data)
        except Exception:
            logger.warning("Failed to load maturity for %s", domain)
            return MaturityState(domain=domain)

    def save(self, state: MaturityState) -> None:
        """Persist maturity state."""
        p = self._path(state.domain)
        p.parent.mkdir(parents=True, exist_ok=True)
        from dataclasses import asdict

        p.write_text(json.dumps(asdict(state), indent=2))

    def record_run(
        self, domain: str, *, success: bool, llm_calls: int
    ) -> MaturityState:
        """Record a run and update maturity."""
        state = self.load(domain)
        state.record_run(success=success, llm_calls=llm_calls)
        self.save(state)
        return state
