"""Dependency injection for the Evolution API."""
from __future__ import annotations

from src.api.session_manager import SessionManager
from src.evolution.db import EvolutionDB
from src.evolution.notifier import Notifier

# Singletons — initialized in lifespan
_db: EvolutionDB | None = None
_notifier: Notifier | None = None
_session_manager: SessionManager | None = None


def set_db(db: EvolutionDB) -> None:
    global _db  # noqa: PLW0603
    _db = db


def set_notifier(notifier: Notifier) -> None:
    global _notifier  # noqa: PLW0603
    _notifier = notifier


def set_session_manager(mgr: SessionManager) -> None:
    global _session_manager  # noqa: PLW0603
    _session_manager = mgr


def get_db() -> EvolutionDB:
    assert _db is not None, "DB not initialized — check lifespan"
    return _db


def get_notifier() -> Notifier:
    assert _notifier is not None, "Notifier not initialized — check lifespan"
    return _notifier


def get_session_manager() -> SessionManager:
    assert _session_manager is not None, "SessionManager not initialized — check lifespan"
    return _session_manager
