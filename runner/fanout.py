"""Browser-level fan-out: many concurrent Solari browser sessions against
one already-provisioned sandbox, isolated by run_id namespacing (see
target/state.py). Concurrency defaults to 3 — the confirmed Free-tier
concurrent-browser limit (see mirage-6-day-plan.md's Budget section) — not
the plan's original 8-16, which needs the Starter tier.

The sandbox itself is one small VM regardless of how wide the fan-out is;
only the browser sessions multiply.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Dict, List, Optional

from agent.models import Model
from runner.score import load_attacks
from runner.single_run import run_once

DEFAULT_CONCURRENCY = 3


async def run_fanout(
    site: str,
    sandbox_state: Dict[str, Any],
    models: List[Model],
    runs_per_cell: int = 3,
    variants: Optional[List[str]] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_steps: int = 15,
    on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    variants = variants or list(load_attacks().keys())
    sem = asyncio.Semaphore(concurrency)
    results: List[Dict[str, Any]] = []
    results_lock = asyncio.Lock()

    async def _one(variant: str, model: Model) -> None:
        run_id = f"f{uuid.uuid4().hex[:10]}"
        async with sem:
            try:
                record = await run_once(
                    site,
                    variant,
                    run_id=run_id,
                    max_steps=max_steps,
                    model=model,
                    sandbox_state=sandbox_state,
                )
            except Exception as e:
                # One flaky call (a real risk — this project has hit two live
                # LLM-provider outages) must not crash the whole fan-out via
                # asyncio.gather() cancelling every other in-flight task.
                # Matches the same fix control.py needed after a live crash.
                record = {
                    "run_id": run_id,
                    "site": site,
                    "variant": variant,
                    "model": model.model_name,
                    "outcome": "error",
                    "weight": None,
                    "error": str(e),
                }
        async with results_lock:
            results.append(record)
        if on_result:
            on_result(record)

    tasks = [
        _one(variant, model)
        for model in models
        for variant in variants
        for _ in range(runs_per_cell)
    ]
    await asyncio.gather(*tasks)
    return results
