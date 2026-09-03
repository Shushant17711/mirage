"""Local backend: the same agent loop and Flask target, no Solari account
needed. Starts the target as a local subprocess, drives it with local
Playwright, and hits the identical /events and /replay-events routes — so
a local run is shaped exactly like a Solari run (same scoring, same replay
format), just without a sandbox, cloud browser, or the previewUrl-recording
workaround (that bug is specific to Solari's own session recording; it
doesn't come up here since there's no Solari session at all).
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, Optional

import httpx
from playwright.async_api import async_playwright

from agent.loop import run_agent
from agent.models import Model
from runner.score import classify, load_attacks
from runner.single_run import REPLAYS_DIR, REPO_ROOT, SITE_TASKS, _record_spend, build_target_url

LOCAL_STATE_DIR = REPO_ROOT / ".mirage_local"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_healthy(base_url: str, attempts: int = 30) -> None:
    async with httpx.AsyncClient() as http:
        for _ in range(attempts):
            try:
                r = await http.get(f"{base_url}/health", timeout=2)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError(f"local target never became healthy at {base_url}/health")


async def run_once_local(
    site: str,
    variant: str,
    run_id: Optional[str] = None,
    max_steps: int = 15,
    model: Optional[Model] = None,
) -> Dict[str, Any]:
    run_id = run_id or f"l{uuid.uuid4().hex[:10]}"
    task = SITE_TASKS[site]
    canary = f"MIRAGE-{run_id}"

    port = _free_port()
    LOCAL_STATE_DIR.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "MIRAGE_EVENTS_PATH": str(LOCAL_STATE_DIR / "events.jsonl"),
        "MIRAGE_REPLAYS_PATH": str(LOCAL_STATE_DIR / "replays"),
    }
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(REPO_ROOT / "target"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base_url = f"http://127.0.0.1:{port}"
    model = model or Model()

    try:
        await _wait_healthy(base_url)
        target_url = build_target_url(base_url, f"/{site}", {"run_id": run_id, "variant": variant})

        t0 = time.time()
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.goto(target_url)
                result = await run_agent(page, task=task, canary=canary, model=model, max_steps=max_steps)
                try:
                    await page.evaluate("window.__mirageFlushReplay && window.__mirageFlushReplay()")
                except Exception:
                    pass
                await asyncio.sleep(1)
            finally:
                await browser.close()
        elapsed = time.time() - t0

        async with httpx.AsyncClient(timeout=10) as http:
            ev_resp = await http.get(build_target_url(base_url, "/events", {"run_id": run_id}))
            events = ev_resp.json() if ev_resp.status_code == 200 else []

            replay_path = None
            replay_resp = await http.get(build_target_url(base_url, "/replay-events", {"run_id": run_id}))
            if replay_resp.status_code == 200 and replay_resp.text.strip():
                REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
                replay_path = REPLAYS_DIR / f"{run_id}.ndjson"
                replay_path.write_text(replay_resp.text)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    attack = load_attacks().get(variant)
    outcome = classify(site, attack, events, result.status, result.summary)

    record = {
        "run_id": run_id,
        "site": site,
        "variant": variant,
        "surface": attack.get("surface") if attack else None,
        "intent": attack.get("intent") if attack else None,
        "status": result.status,
        "summary": result.summary,
        "outcome": outcome.label,
        "weight": outcome.weight,
        "steps": result.steps,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cost_usd": round(result.cost_usd, 6),
        "elapsed_s": round(elapsed, 1),
        "events": events,
        "replay_path": str(replay_path.relative_to(REPO_ROOT)) if replay_path else None,
        "model": model.model_name,
        "backend": "local",
    }
    _record_spend(
        {
            "run_id": run_id,
            "model": model.model_name,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cost_usd": record["cost_usd"],
        }
    )
    return record
