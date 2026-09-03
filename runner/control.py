"""The isolation control: measure whether run_id namespacing produces the
same outcomes as true per-run machine isolation, instead of just assuming
it does. `revert()` is broken (see provision.py's note), so "true machine
isolation" here means: kill the sandbox and create a fresh one from the
warm snapshot before every single run — confirmed live (2026-09-02) to
correctly resume the already-running target server, not just its files.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from agent.models import Model
from runner.provision import provision, teardown
from runner.single_run import run_once


async def run_control(
    site: str,
    variants: List[str],
    model: Model,
    snapshot_id: str,
    runs_per_cell: int = 3,
    max_steps: int = 15,
    on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """Serial, full-reset runs for each variant in `variants`: kill and
    recreate the sandbox from `snapshot_id` before every single run — the
    expensive, ground-truth isolation method the namespaced fan-out is
    measured against.

    Each run's sandbox costs a real VM boot, so a run is reported via
    `on_result` (and teardown happens) the moment it finishes — an
    unhandled crash partway through must not lose the runs that already
    completed. A single run's own failure (a flaky LLM provider, seen live
    mid-testing) is recorded as an "error" outcome and the loop continues
    rather than aborting the whole control sample."""
    results = []
    for variant in variants:
        for _ in range(runs_per_cell):
            sandbox_state = await provision(from_snapshot=snapshot_id, save_state=False)
            try:
                run_id = f"c{uuid.uuid4().hex[:10]}"
                try:
                    record = await run_once(
                        site,
                        variant,
                        run_id=run_id,
                        max_steps=max_steps,
                        model=model,
                        sandbox_state=sandbox_state,
                    )
                    record["control_mode"] = "serial_full_reset"
                except Exception as e:  # any failure here becomes an "error" outcome, not a crash
                    record = {
                        "run_id": run_id,
                        "site": site,
                        "variant": variant,
                        "model": model.model_name,
                        "outcome": "error",
                        "weight": None,
                        "error": str(e),
                        "control_mode": "serial_full_reset",
                    }
            finally:
                await teardown(sandbox_state["sandbox_id"])
            results.append(record)
            if on_result:
                on_result(record)
    return results


def agreement_rate(
    control_records: List[Dict[str, Any]],
    fanout_records: List[Dict[str, Any]],
    model_name: str,
) -> Dict[str, Any]:
    """For each variant present in both sets, compare the modal (most
    common) outcome label between the expensive serial-reset method and the
    concurrent namespaced method."""

    def _modal_by_variant(records: List[Dict[str, Any]]) -> Dict[str, str]:
        by_variant: Dict[str, Counter] = {}
        for r in records:
            if r.get("model") != model_name or r.get("outcome") == "error":
                continue
            by_variant.setdefault(r["variant"], Counter())[r["outcome"]] += 1
        return {v: c.most_common(1)[0][0] for v, c in by_variant.items() if c}

    control_modal = _modal_by_variant(control_records)
    fanout_modal = _modal_by_variant(fanout_records)

    detail = []
    agree = 0
    for variant, control_outcome in control_modal.items():
        if variant not in fanout_modal:
            continue
        fanout_outcome = fanout_modal[variant]
        matches = control_outcome == fanout_outcome
        agree += int(matches)
        detail.append(
            {
                "variant": variant,
                "control_outcome": control_outcome,
                "fanout_outcome": fanout_outcome,
                "agrees": matches,
            }
        )

    n = len(detail)
    return {
        "n_variants_compared": n,
        "agreement_rate": round(agree / n, 3) if n else None,
        "detail": detail,
    }
