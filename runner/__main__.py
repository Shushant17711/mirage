"""CLI:
  python -m runner --backend solari --site support --variant clean
  python -m runner --backend solari --fanout --site support --runs 3 \
      --models minimax-m3-free,qwen3.8-27b
  python -m runner --backend solari --control --site support --runs 3 \
      --control-sample S1I2,S2I3,S1I1,S3I4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from typing import List, Optional

from agent.models import Model
from runner.control import agreement_rate, run_control
from runner.fanout import run_fanout
from runner.provision import STATE_PATH, provision
from runner.score import load_attacks
from runner.single_run import run_once

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "results" / "results.jsonl"
CONTROL_RESULTS_PATH = REPO_ROOT / "results" / "control.json"


def _append_result(record: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def _read_results() -> List[dict]:
    if not RESULTS_PATH.exists():
        return []
    with open(RESULTS_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def _print_table(records: list) -> None:
    print(f"\n{'model':<18} {'variant':<10} {'outcome':<18} {'weight':<8} {'steps':<6} summary")
    for r in records:
        w = "-" if r.get("weight") is None else f"{r['weight']:.1f}"
        print(
            f"{r.get('model', ''):<18} {r['variant']:<10} {r['outcome']:<18} {w:<8} "
            f"{r.get('steps', '-'):<6} {(r.get('summary') or r.get('error') or '')[:50]}"
        )

    n_errors = sum(1 for r in records if r["outcome"] == "error")
    if n_errors:
        print(f"\n({n_errors} run(s) errored — excluded from the metrics below)")

    by_model: dict = {}
    for r in records:
        if r["outcome"] != "error":
            by_model.setdefault(r.get("model"), []).append(r)

    for model_name, recs in by_model.items():
        attack_runs = [r for r in recs if r["variant"] != "clean"]
        clean_runs = [r for r in recs if r["variant"] == "clean"]
        print(f"\n== {model_name} ==")
        if attack_runs:
            resistance = 1 - sum(r["weight"] for r in attack_runs) / len(attack_runs)
            print(f"  Injection Resistance: {resistance:.2f}  (n={len(attack_runs)} attack runs)")
        if clean_runs:
            utility = sum(1 for r in clean_runs if r["outcome"] == "clean_pass") / len(clean_runs)
            print(f"  Benign Utility:       {utility:.2f}  (n={len(clean_runs)} control runs)")


async def cmd_all(site: str, runs: int, max_steps: int) -> None:
    attack_ids = list(load_attacks().keys())
    records = []
    for attack_id in attack_ids:
        for i in range(runs):
            run_id = f"m{uuid.uuid4().hex[:10]}"
            print(f"running {attack_id} ({i + 1}/{runs})...", flush=True)
            try:
                record = await run_once(site, attack_id, run_id=run_id, max_steps=max_steps)
            except Exception as e:
                # One flaky provider call must not abort the rest of a
                # serial matrix pass — see the same fix in fanout.py.
                record = {
                    "run_id": run_id,
                    "site": site,
                    "variant": attack_id,
                    "model": Model().model_name,
                    "outcome": "error",
                    "weight": None,
                    "error": str(e),
                }
            _append_result(record)
            records.append(record)
            print(f"  -> {record['outcome']} (status={record.get('status', 'n/a')})", flush=True)
    _print_table(records)


async def cmd_fanout(
    site: str,
    runs: int,
    max_steps: int,
    model_names: List[str],
    concurrency: int,
    variants: Optional[List[str]] = None,
) -> None:
    sandbox_state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else await provision()
    models = [Model(model_name=name) for name in model_names]
    variants = variants or list(load_attacks().keys())

    def on_result(record: dict) -> None:
        _append_result(record)
        print(f"  {record['model']:<18} {record['variant']:<8} -> {record['outcome']}", flush=True)

    print(
        f"fanning out {len(model_names)} model(s) x {len(variants)} variants x "
        f"{runs} runs, concurrency={concurrency}...",
        flush=True,
    )
    records = await run_fanout(
        site,
        sandbox_state,
        models,
        runs_per_cell=runs,
        variants=variants,
        concurrency=concurrency,
        max_steps=max_steps,
        on_result=on_result,
    )
    _print_table(records)


async def cmd_control(site: str, runs: int, max_steps: int, sample: List[str], model_name: str) -> None:
    if not STATE_PATH.exists():
        raise SystemExit("no sandbox state found — run a fan-out or single pass first")
    sandbox_state = json.loads(STATE_PATH.read_text())
    snapshot_id = sandbox_state.get("snapshot_id")
    if not snapshot_id:
        raise SystemExit("no snapshot_id in sandbox state — can't run the isolation control")

    model = Model(model_name=model_name)
    print(f"running isolation control: {len(sample)} variants x {runs} runs, serial, full reset each time...", flush=True)

    def on_result(record: dict) -> None:
        _append_result(record)
        print(f"  {record['variant']:<8} -> {record['outcome']} (control)", flush=True)

    control_records = await run_control(
        site, sample, model, snapshot_id, runs_per_cell=runs, max_steps=max_steps, on_result=on_result
    )

    fanout_records = [r for r in _read_results() if r.get("control_mode") is None]
    result = agreement_rate(control_records, fanout_records, model_name)
    CONTROL_RESULTS_PATH.write_text(json.dumps(result, indent=2))
    print(f"\nIsolation control agreement rate: {result['agreement_rate']} "
          f"(n={result['n_variants_compared']} variants compared)")
    for d in result["detail"]:
        mark = "OK" if d["agrees"] else "MISMATCH"
        print(f"  [{mark}] {d['variant']}: control={d['control_outcome']} fanout={d['fanout_outcome']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["solari", "local"], default="solari")
    parser.add_argument("--site", choices=["support", "shop", "mail"], default="support")
    parser.add_argument("--variant", default="clean")
    parser.add_argument("--all", action="store_true", help="run every attack in attacks.yaml, serially, one model")
    parser.add_argument("--fanout", action="store_true", help="concurrent fan-out across models/variants/runs")
    parser.add_argument("--control", action="store_true", help="serial isolation control with full reset per run")
    parser.add_argument("--control-sample", default="S1I1,S1I2,S2I3,S3I4", help="comma-separated variant ids for --control")
    parser.add_argument("--models", default=None, help="comma-separated model names, used with --fanout")
    parser.add_argument("--variants", default=None, help="comma-separated variant ids to restrict --fanout to (default: all)")
    parser.add_argument("--runs", type=int, default=1, help="repeats per cell")
    parser.add_argument("--concurrency", type=int, default=3, help="concurrent browser sessions for --fanout")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-steps", type=int, default=15)
    args = parser.parse_args()

    if args.backend == "local":
        if args.fanout or args.control or args.all:
            raise SystemExit(
                "backend=local only supports a single run (no --fanout/--control/--all — "
                "those need a Solari account). Use --backend solari for the full matrix."
            )
        from runner.local_backend import run_once_local

        record = asyncio.run(
            run_once_local(args.site, args.variant, run_id=args.run_id, max_steps=args.max_steps)
        )
        print(json.dumps(record, indent=2))
        return

    if args.fanout:
        names = args.models.split(",") if args.models else [Model().model_name]
        variants = args.variants.split(",") if args.variants else None
        asyncio.run(cmd_fanout(args.site, args.runs, args.max_steps, names, args.concurrency, variants=variants))
        return

    if args.control:
        model_name = args.models.split(",")[0] if args.models else Model().model_name
        sample = args.control_sample.split(",")
        asyncio.run(cmd_control(args.site, args.runs, args.max_steps, sample, model_name))
        return

    if args.all:
        asyncio.run(cmd_all(args.site, args.runs, args.max_steps))
        return

    record = asyncio.run(
        run_once(args.site, args.variant, run_id=args.run_id, max_steps=args.max_steps)
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
