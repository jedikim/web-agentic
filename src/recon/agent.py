"""ReconAgent — LangGraph state machine for site reconnaissance.

State flow::

    CheckKB → (cached?) → ReturnProfile
           → (miss/expired) → DOMScan → VisualScan → NavScan → Synthesize → SaveToKB → Done
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from src.kb.manager import KBManager
from src.recon.dom_scanner import DOMScanner
from src.recon.nav_scanner import NavScanner
from src.recon.profile_synthesizer import ProfileSynthesizer
from src.recon.visual_scanner import VisualScanner

logger = logging.getLogger(__name__)


class ReconState(TypedDict, total=False):
    """State for the ReconAgent graph."""

    domain: str
    browser: Any  # BrowserLike
    detector: Any  # DetectorLike | None
    vlm: Any  # VLMLike | None
    llm: Any  # LLMLike | None
    kb: KBManager
    dom_result: dict[str, Any] | None
    visual_result: dict[str, Any] | None
    nav_result: dict[str, Any] | None
    site_profile: Any  # SiteProfile | None
    error: str | None
    recon_stage: str  # "check_kb" | "dom" | "visual" | "nav" | "synthesize" | "done"


async def check_kb(state: ReconState) -> ReconState:
    """Check if KB has a fresh profile."""
    kb: KBManager = state["kb"]
    profile = kb.load_profile(state["domain"])
    if profile and not kb.is_profile_expired(profile):
        logger.info("KB hit for %s (v%d)", state["domain"], profile.recon_version)
        return {**state, "site_profile": profile, "recon_stage": "done"}
    logger.info("KB miss for %s, starting recon", state["domain"])
    return {**state, "recon_stage": "dom"}


async def dom_scan(state: ReconState) -> ReconState:
    """Stage 1: DOM scan."""
    scanner = DOMScanner()
    try:
        result = await scanner.scan(state["browser"])
        return {**state, "dom_result": result, "recon_stage": "visual"}
    except Exception as e:
        logger.error("DOM scan failed: %s", e)
        return {**state, "error": str(e), "recon_stage": "done"}


async def visual_scan(state: ReconState) -> ReconState:
    """Stage 2: Visual scan."""
    scanner = VisualScanner()
    try:
        result = await scanner.scan(
            state["browser"],
            state.get("dom_result") or {},
            detector=state.get("detector"),
            vlm=state.get("vlm"),
        )
        return {**state, "visual_result": result, "recon_stage": "nav"}
    except Exception as e:
        logger.warning("Visual scan failed: %s", e)
        return {**state, "visual_result": {}, "recon_stage": "nav"}


async def nav_scan(state: ReconState) -> ReconState:
    """Stage 3: Navigation scan."""
    scanner = NavScanner()
    try:
        result = await scanner.scan(
            state["browser"],
            state.get("dom_result") or {},
        )
        return {**state, "nav_result": result, "recon_stage": "synthesize"}
    except Exception as e:
        logger.warning("Nav scan failed: %s", e)
        return {**state, "nav_result": {}, "recon_stage": "synthesize"}


async def synthesize_profile(state: ReconState) -> ReconState:
    """Combine all scan results into SiteProfile."""
    synthesizer = ProfileSynthesizer()
    kb: KBManager = state["kb"]

    existing = kb.load_profile(state["domain"])
    existing_version = existing.recon_version if existing else 0

    try:
        profile = await synthesizer.synthesize(
            domain=state["domain"],
            dom_result=state.get("dom_result") or {},
            visual_result=state.get("visual_result") or {},
            nav_result=state.get("nav_result") or {},
            llm=state.get("llm"),
            existing_version=existing_version,
        )
        return {**state, "site_profile": profile, "recon_stage": "done"}
    except Exception as e:
        logger.error("Profile synthesis failed: %s", e)
        return {**state, "error": str(e), "recon_stage": "done"}


async def save_to_kb(state: ReconState) -> ReconState:
    """Save profile to KB."""
    if state.get("site_profile") and state.get("kb"):
        kb: KBManager = state["kb"]
        kb.save_profile(state["site_profile"])
        logger.info(
            "Saved profile for %s v%d",
            state["domain"],
            state["site_profile"].recon_version,
        )
    return state


def route_stage(state: ReconState) -> str:
    """Route to next node based on recon_stage."""
    stage = state.get("recon_stage", "done")
    if stage == "done":
        return "save_and_return"
    return stage


def build_recon_graph() -> Any:
    """Build and compile the ReconAgent LangGraph.

    Returns:
        Compiled LangGraph runnable, or None if langgraph not installed.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        logger.warning("langgraph not installed; ReconAgent graph unavailable")
        return None

    graph = StateGraph(ReconState)

    graph.add_node("check_kb", check_kb)
    graph.add_node("dom", dom_scan)
    graph.add_node("visual", visual_scan)
    graph.add_node("nav", nav_scan)
    graph.add_node("synthesize", synthesize_profile)
    graph.add_node("save_and_return", save_to_kb)

    graph.add_edge(START, "check_kb")
    graph.add_conditional_edges("check_kb", route_stage)
    graph.add_edge("dom", "visual")
    graph.add_edge("visual", "nav")
    graph.add_edge("nav", "synthesize")
    graph.add_conditional_edges("synthesize", route_stage)
    graph.add_edge("save_and_return", END)

    return graph.compile()


async def run_recon(
    domain: str,
    browser: Any,
    kb: KBManager,
    *,
    detector: Any = None,
    vlm: Any = None,
    llm: Any = None,
) -> Any:
    """Run the full recon pipeline (with or without LangGraph).

    Falls back to sequential execution if LangGraph is not installed.

    Args:
        domain: Target site domain.
        browser: Browser instance.
        kb: Knowledge Base manager.
        detector: Optional local object detector.
        vlm: Optional VLM client.
        llm: Optional LLM router.

    Returns:
        SiteProfile or None.
    """
    initial_state: ReconState = {
        "domain": domain,
        "browser": browser,
        "detector": detector,
        "vlm": vlm,
        "llm": llm,
        "kb": kb,
        "dom_result": None,
        "visual_result": None,
        "nav_result": None,
        "site_profile": None,
        "error": None,
        "recon_stage": "check_kb",
    }

    graph = build_recon_graph()
    if graph is not None:
        result = await graph.ainvoke(initial_state)
        return result.get("site_profile")

    # Fallback: sequential execution
    logger.info("Running recon sequentially (no LangGraph)")
    state = await check_kb(initial_state)
    if state.get("recon_stage") == "done":
        return state.get("site_profile")

    state = await dom_scan(state)
    if state.get("error"):
        return None

    state = await visual_scan(state)
    state = await nav_scan(state)
    state = await synthesize_profile(state)
    state = await save_to_kb(state)
    return state.get("site_profile")
