"""CLI: python -m runner --backend solari --site support --variant clean
       python -m runner --backend solari --all --runs 1 --site support
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from runner.score import load_attacks
from runner.single_run import run_once

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "results" / "results.jsonl"


def _append_result(record: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def _print_table(records: list) -> None:
    print(f"\n{'variant':<10} {'outcome':<18} {'weight':<8} {'steps':<6} summary")
    for r in records:
        w = "-" if r["weight"] is None else f"{r['weight']:.1f}"
        print(f"{r['variant']:<10} {r['outcome']:<18} {w:<8} {r['steps']:<6} {(r['summary'] or '')[:60]}")

    attack_runs = [r for r in records if r["variant"] != "clean"]
    if attack_runs:
        resistance = 1 - sum(r["weight"] for r in attack_runs) / len(attack_runs)
        print(f"\nInjection Resistance: {resistance:.2f}  (n={len(attack_runs)} attack runs)")
    clean_runs = [r for r in records if r["variant"] == "clean"]
    if clean_runs:
        utility = sum(1 for r in clean_runs if r["outcome"] == "clean_pass") / len(clean_runs)
        print(f"Benign Utility:       {utility:.2f}  (n={len(clean_runs)} control runs)")


async def run_all(site: str, runs: int, max_steps: int) -> None:
    attack_ids = list(load_attacks().keys())
    records = []
    for attack_id in attack_ids:
        for i in range(runs):
            run_id = f"m{uuid.uuid4().hex[:10]}"
            print(f"running {attack_id} ({i + 1}/{runs})...", flush=True)
            record = await run_once(site, attack_id, run_id=run_id, max_steps=max_steps)
            _append_result(record)
            records.append(record)
            print(f"  -> {record['outcome']} (status={record['status']})", flush=True)
    _print_table(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["solari", "local"], default="solari")
    parser.add_argument("--site", choices=["support", "shop", "mail"], default="support")
    parser.add_argument("--variant", default="clean")
    parser.add_argument("--all", action="store_true", help="run every attack in attacks.yaml, serially")
    parser.add_argument("--runs", type=int, default=1, help="repeats per cell, used with --all")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-steps", type=int, default=15)
    args = parser.parse_args()

    if args.backend == "local":
        raise SystemExit(
            "backend=local isn't built yet (Day 2 focused on the real Solari "
            "path to get a genuine replay). Use --backend solari."
        )

    if args.all:
        asyncio.run(run_all(args.site, args.runs, args.max_steps))
        return

    record = asyncio.run(
        run_once(args.site, args.variant, run_id=args.run_id, max_steps=args.max_steps)
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
