"""Provision the target sandbox: upload target/, install deps, start the
Flask server, expose it via previewUrl, and take a "warm" snapshot once it's
healthy.

NOTE on snapshot/revert: live testing against the real API on 2026-09-02
found `sandbox.revert(snapshot_id)` unreliable — it fails with an
undocumented `409 Not revertable` even immediately after a successful
`snapshot()`, on a freshly booted sandbox, while paused, and via a snapshot's
own `from_snapshot` lineage. `snapshot()` and `create(from_snapshot=...)`
both work correctly. So "restore the world" here means: kill the current
sandbox and create a fresh one `from_snapshot`, not call `.revert()`. This
also means the previewUrl changes every reset — callers must re-fetch it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from solari_sandbox import SandboxClient

BASE_URL = "https://api.getsolari.com"
PORT = 3000
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / ".mirage_sandbox.json"


def _client() -> SandboxClient:
    return SandboxClient(api_key=os.environ["SOLARI_API_KEY"], base_url=BASE_URL)


async def _upload_target(sandbox) -> None:
    await sandbox.files.write(
        "/tmp/site/attacks.yaml",
        (REPO_ROOT / "attacks.yaml").read_text(),
    )
    target_dir = REPO_ROOT / "target"
    await sandbox.files.write("/tmp/site/target/app.py", (target_dir / "app.py").read_text())
    await sandbox.files.write("/tmp/site/target/state.py", (target_dir / "state.py").read_text())
    await sandbox.files.write(
        "/tmp/site/target/requirements.txt",
        (target_dir / "requirements.txt").read_text(),
    )
    for tpl in (target_dir / "templates").glob("*.html"):
        await sandbox.files.write(f"/tmp/site/target/templates/{tpl.name}", tpl.read_text())


async def _install_and_start(sandbox) -> None:
    r = await sandbox.commands.run(
        "python3", args=["-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
        cwd="/tmp/site/target",
    )
    if r.exitCode != 0:
        raise RuntimeError(f"pip install failed: {r.stderr}")

    await sandbox.commands.run(
        "python3", args=["app.py"],
        cwd="/tmp/site/target",
        env={"PORT": str(PORT), "MIRAGE_EVENTS_PATH": "/tmp/site/events.jsonl"},
        background=True,
    )


async def _wait_healthy(url: str, attempts: int = 20) -> None:
    import httpx

    async with httpx.AsyncClient() as http:
        for i in range(attempts):
            try:
                res = await http.get(f"{url}/health", timeout=5)
                if res.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(1.5)
    raise RuntimeError(f"target never became healthy at {url}/health")


async def provision(
    from_snapshot: Optional[str] = None,
    timeout_ms: int = 15 * 60_000,
    save_state: bool = True,
) -> dict:
    client = _client()
    try:
        sandbox = await client.create(
            template="base", timeout_ms=timeout_ms, from_snapshot=from_snapshot,
        )
    except Exception:
        await client.aclose()
        raise

    try:
        await sandbox.connect()

        if from_snapshot is None:
            await _upload_target(sandbox)
            await _install_and_start(sandbox)

        info = await sandbox.preview_url(PORT)
        url = info["url"]
        await _wait_healthy(url)

        # Live-tested 2026-09-02: snapshot() reliably fails with an
        # undocumented `409 Not snapshottable` once the target's background
        # Flask process is running — reproducible on a fresh sandbox with no
        # prior snapshots, so not an account quota issue. Treated as
        # non-fatal here since the from_snapshot() reset path (see the
        # revert() workaround note above) already can't be used for a warm
        # sandbox with a live server either way; a snapshot_id of None just
        # means Day 4's reset falls back to a full re-provision.
        snapshot_id = None
        if from_snapshot is None:
            try:
                snapshot_id = await sandbox.snapshot("warm")
            except Exception as e:  # non-fatal — see the comment above this block
                print(f"warning: snapshot('warm') failed, continuing without one: {e}")
    except Exception:
        await sandbox.kill()
        await client.aclose()
        raise

    result = {
        "sandbox_id": sandbox.sandboxId,
        "preview_url": url,
        "snapshot_id": snapshot_id or from_snapshot,
    }
    if save_state:
        STATE_PATH.write_text(json.dumps(result, indent=2))
    await client.aclose()
    return result


async def teardown(sandbox_id: Optional[str] = None) -> None:
    client = _client()
    read_from_state = sandbox_id is None
    if read_from_state:
        if not STATE_PATH.exists():
            print("no saved sandbox state, nothing to tear down")
            await client.aclose()
            return
        sandbox_id = json.loads(STATE_PATH.read_text())["sandbox_id"]
    await client.kill(sandbox_id)
    print(f"killed {sandbox_id}")
    # Only clear the shared state file when we read the id from it — an
    # explicit sandbox_id (e.g. control.py's disposable sandboxes) must
    # never delete an unrelated fanout run's saved state.
    if read_from_state and STATE_PATH.exists():
        STATE_PATH.unlink()
    await client.aclose()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "teardown":
        asyncio.run(teardown())
    else:
        result = asyncio.run(provision())
        print(json.dumps(result, indent=2))
