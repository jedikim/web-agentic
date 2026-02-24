"""Scenario report generator — per-scenario report.md + overall summary.md.

Creates human-readable Markdown reports documenting each phase's execution,
including step-by-step results and embedded screenshot references.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from scripts.scenario_types import PhaseResult, ScenarioResult

logger = logging.getLogger(__name__)


def _status_label(pr: PhaseResult) -> str:
    if pr.timed_out:
        return "TIMEOUT"
    if pr.error:
        return "ERROR"
    if pr.run_result is None:
        return "SKIP"
    return "OK" if pr.run_result.success else "FAIL"


def _phase_steps_ok(pr: PhaseResult) -> int:
    if pr.run_result is None:
        return 0
    return sum(1 for sr in pr.run_result.step_results if sr.success)


def _phase_steps_all(pr: PhaseResult) -> int:
    if pr.run_result is None:
        return 0
    return len(pr.run_result.step_results)


def _phase_cost(pr: PhaseResult) -> float:
    if pr.run_result is None:
        return 0.0
    return pr.run_result.total_cost_usd


def _phase_tokens(pr: PhaseResult) -> int:
    if pr.run_result is None:
        return 0
    return pr.run_result.total_tokens


# ── Per-Scenario Report ──────────────────────────────


def write_scenario_report(result: ScenarioResult, out_dir: Path) -> Path:
    """Write a detailed ``report.md`` for a single scenario.

    Args:
        result: Completed scenario result.
        out_dir: Directory for this scenario (e.g. ``testing/scenarios/family_outing/``).

    Returns:
        Path to the written report file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"

    lines: list[str] = []
    sc = result.scenario

    # Header
    overall = "SUCCESS" if result.overall_success else "PARTIAL" if any(
        pr.run_result and pr.run_result.success for pr in result.phase_results
    ) else "FAILED"
    lines.append(f"# {sc.name}")
    lines.append(f"_{sc.description}_")
    lines.append("")
    lines.append(f"**Context**: {sc.context}")
    lines.append(f"**Status**: {overall}")
    lines.append(
        f"**Total time**: {result.total_wall_time_s:.1f}s | "
        f"**Cost**: ${result.total_cost_usd:.4f} | "
        f"**Tokens**: {result.total_tokens:,}"
    )
    lines.append(
        f"**Steps**: {result.total_steps_ok}/{result.total_steps_all} succeeded"
    )
    lines.append(f"**Started**: {result.started_at} | **Finished**: {result.finished_at}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-phase details
    ss_dir = out_dir / "screenshots"
    for pi, pr in enumerate(result.phase_results, 1):
        phase = pr.phase
        status = _status_label(pr)
        steps_ok = _phase_steps_ok(pr)
        steps_all = _phase_steps_all(pr)
        cost = _phase_cost(pr)

        lines.append(f"## Phase {pi}: {phase.name}")
        lines.append(f"**Intent**: {phase.intent}")
        if phase.url:
            lines.append(f"**URL**: {phase.url}")
        lines.append(
            f"**Result**: {status} — {steps_ok}/{steps_all} steps | "
            f"${cost:.4f} | {pr.wall_time_s:.1f}s"
        )
        lines.append("")

        if pr.timed_out:
            lines.append(f"> Phase timed out after {phase.timeout_s}s")
            lines.append("")
        if pr.error:
            lines.append(f"> Error: {pr.error}")
            lines.append("")

        # Show rescued screenshots for timeout/error phases (no run_result)
        if pr.run_result is None and ss_dir.exists():
            prefix = f"phase{pi}_"
            orphan_ss = sorted(ss_dir.glob(f"{prefix}*.png"))
            if orphan_ss:
                lines.append("### Screenshots (captured before timeout/error)")
                lines.append("")
                for ss in orphan_ss:
                    rel = ss.relative_to(out_dir)
                    lines.append(f"![{ss.stem}]({rel})")
                lines.append("")

        # Step details
        if pr.run_result:
            rr = pr.run_result
            planned = {s.step_id: s for s in rr.planned_steps}
            for si, sr in enumerate(rr.step_results, 1):
                step_def = planned.get(sr.step_id)
                intent_text = step_def.intent if step_def else sr.step_id
                ok_mark = "OK" if sr.success else "FAIL"
                lines.append(
                    f"### Step {si}: {sr.step_id} — {intent_text}"
                )
                lines.append(
                    f"- Method: {sr.method} | Result: {ok_mark} | "
                    f"Latency: {sr.latency_ms:.0f}ms"
                )

                # Find matching screenshots
                prefix = f"phase{pi}_step_{si}_"
                matching_ss = sorted(ss_dir.glob(f"{prefix}*.png")) if ss_dir.exists() else []
                for ss in matching_ss:
                    rel = ss.relative_to(out_dir)
                    lines.append(f"![{sr.step_id}]({rel})")
                lines.append("")

        lines.append("---")
        lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Phase | Name | Steps | Status | Cost | Time |")
    lines.append("|-------|------|-------|--------|------|------|")
    for pi, pr in enumerate(result.phase_results, 1):
        status = _status_label(pr)
        so = _phase_steps_ok(pr)
        sa = _phase_steps_all(pr)
        cost = _phase_cost(pr)
        lines.append(
            f"| {pi} | {pr.phase.name} | {so}/{sa} | {status} | "
            f"${cost:.4f} | {pr.wall_time_s:.1f}s |"
        )
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote scenario report: %s", report_path)
    return report_path


# ── Overall Summary ──────────────────────────────────


def write_summary(results: list[ScenarioResult], out_dir: Path) -> Path:
    """Write ``summary.md`` covering all executed scenarios.

    Args:
        results: List of scenario results.
        out_dir: Root testing directory (e.g. ``testing/``).

    Returns:
        Path to the written summary file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.md"

    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append("# Scenario Test Summary")
    lines.append(f"_Generated: {now}_")
    lines.append("")

    total_ok = sum(1 for r in results if r.overall_success)
    total = len(results)
    total_cost = sum(r.total_cost_usd for r in results)
    total_tokens = sum(r.total_tokens for r in results)
    total_time = sum(r.total_wall_time_s for r in results)
    total_steps_ok = sum(r.total_steps_ok for r in results)
    total_steps_all = sum(r.total_steps_all for r in results)

    lines.append(f"**Scenarios**: {total_ok}/{total} passed")
    lines.append(f"**Steps**: {total_steps_ok}/{total_steps_all} succeeded")
    lines.append(
        f"**Total cost**: ${total_cost:.4f} | "
        f"**Tokens**: {total_tokens:,} | "
        f"**Time**: {total_time:.1f}s"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Scenario table
    lines.append("| Scenario | Phases | Steps | Status | Cost | Time |")
    lines.append("|----------|--------|-------|--------|------|------|")
    for r in results:
        status = "PASS" if r.overall_success else "FAIL"
        phases_ok = sum(
            1 for pr in r.phase_results
            if pr.run_result and pr.run_result.success
        )
        phases_all = len(r.phase_results)
        lines.append(
            f"| {r.scenario.name} | {phases_ok}/{phases_all} | "
            f"{r.total_steps_ok}/{r.total_steps_all} | {status} | "
            f"${r.total_cost_usd:.4f} | {r.total_wall_time_s:.1f}s |"
        )
    lines.append("")

    # Per-scenario detail
    for r in results:
        status = "PASS" if r.overall_success else "FAIL"
        lines.append(f"### {r.scenario.name} — {status}")
        lines.append(f"_{r.scenario.description}_")
        lines.append("")
        for pi, pr in enumerate(r.phase_results, 1):
            ps = _status_label(pr)
            so = _phase_steps_ok(pr)
            sa = _phase_steps_all(pr)
            lines.append(
                f"  {pi}. **{pr.phase.name}**: {ps} ({so}/{sa} steps, {pr.wall_time_s:.1f}s)"
            )
        lines.append("")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote summary: %s", summary_path)
    return summary_path


# ── Machine-Readable Log ─────────────────────────────


def write_run_log(results: list[ScenarioResult], out_dir: Path) -> Path:
    """Write ``run_log.json`` with machine-readable results.

    Args:
        results: List of scenario results.
        out_dir: Root testing directory.

    Returns:
        Path to the written JSON file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run_log.json"

    entries = []
    for r in results:
        phases = []
        for pr in r.phase_results:
            phase_entry: dict = {
                "name": pr.phase.name,
                "intent": pr.phase.intent,
                "url": pr.phase.url,
                "status": _status_label(pr),
                "wall_time_s": round(pr.wall_time_s, 2),
                "steps_ok": _phase_steps_ok(pr),
                "steps_all": _phase_steps_all(pr),
                "cost_usd": round(_phase_cost(pr), 6),
                "tokens": _phase_tokens(pr),
            }
            if pr.error:
                phase_entry["error"] = pr.error
            if pr.timed_out:
                phase_entry["timed_out"] = True
            phases.append(phase_entry)

        entries.append({
            "scenario": r.scenario.name,
            "description": r.scenario.description,
            "overall_success": r.overall_success,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "total_wall_time_s": round(r.total_wall_time_s, 2),
            "total_tokens": r.total_tokens,
            "total_cost_usd": round(r.total_cost_usd, 6),
            "total_steps_ok": r.total_steps_ok,
            "total_steps_all": r.total_steps_all,
            "phases": phases,
        })

    log_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote run log: %s", log_path)
    return log_path
