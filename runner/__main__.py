"""CLI: python -m runner --backend solari --site support --variant clean"""

from __future__ import annotations

import argparse
import asyncio
import json

from runner.single_run import run_once


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["solari", "local"], default="solari")
    parser.add_argument("--site", choices=["support", "shop", "mail"], default="support")
    parser.add_argument("--variant", default="clean")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-steps", type=int, default=15)
    args = parser.parse_args()

    if args.backend == "local":
        raise SystemExit(
            "backend=local isn't built yet (Day 2 focused on the real Solari "
            "path to get a genuine replay). Use --backend solari."
        )

    record = asyncio.run(
        run_once(args.site, args.variant, run_id=args.run_id, max_steps=args.max_steps)
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
