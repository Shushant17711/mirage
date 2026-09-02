# Build prompt for a fresh session

Paste everything below into a new Claude Code session, started in
`/home/shushant/Projects/Solari`.

---

I'm building Mirage for the Pinetree Research / Solari "build something real, get
hired" challenge. Full plan and README are already written in this directory —
read them first, don't re-derive the design:

- `mirage-6-day-plan.md` — the day-by-day build plan. This is the source of
  truth for architecture, scope, and sequencing.
- `README.md` — the target repo README, partially filled with `<!-- FILL -->`
  markers for what only exists once the thing is built. Do not remove a FILL
  marker without replacing it with something that actually ran.
- `PLAN-REVISION.md` — superseded by the plan above, kept for the research
  trail. Skim only if something in the plan is unclear and you want the "why."

## What Mirage is, in one paragraph

A synthetic adversarial web for measuring how browser agents fail. It hosts a
small Flask app (a support portal, a storefront, a webmail client) inside a
Solari sandbox, exposed on a public URL via `previewUrl`. Prompt-injection
payloads are planted across the pages via a `?variant=` parameter. A minimal
browser agent (your own tool-calling loop, not a commercial product) is pointed
at it with a benign task and a secret canary token, driven through concurrent
Solari cloud browser sessions with `recording=True`. Outcomes are graded
server-side (canary hit, honeypot click) — never by an LLM judge. Results:
`results.jsonl`, a resistance-vs-utility scatter, and every replay downloaded
and committed to the repo as rrweb NDJSON with a static player, because Solari
replay retention is too short (1 day Free, 7 Starter) to link to reliably.

## Non-negotiable architecture calls — already made, do not relitigate

These were reached after checking the actual Solari docs, pricing, and
concurrency limits against the original plan, which got them wrong. Don't
re-derive from scratch; if you think one is wrong, say so and cite what changed.

1. **Fan out on concurrent browser sessions, not concurrent sandboxes.**
   Sandboxes cap at 1-2 concurrent on Free/Starter; browsers cap at 3-20. One
   sandbox hosts the targets for the whole run.
2. **Targets carry real mutable state, namespaced by `run_id`.** Not stateless
   `?variant=` rendering alone — a webmail outbox that accumulates sent mail, a
   ticket queue the agent can post into. This is what makes snapshot/`revert()`
   load-bearing instead of decorative.
3. **Run the isolation control.** After the main matrix, re-run a sample of
   cells serially with `revert("warm")` before every single run and compare
   outcomes against the namespaced concurrent runs. Report the agreement rate.
   This is the strongest methodological claim in the project — don't skip it
   under time pressure without saying so explicitly.
4. **Commit every replay to the repo** (`results/replays/*.ndjson`) with a
   static rrweb player (`results/player.html`). Never rely on a live Solari
   replay link in the README.
5. **Grade server-side only.** No LLM judges an outcome, ever.
6. **The headline is a finding, not an infra benchmark.** Don't lead with
   serial-vs-parallel timing. Lead with compromise rate by surface, or the
   resistance-vs-utility frontier.
7. **No computer-use / Desktop agent in this build.** It's the most interesting
   follow-up (a pixel-driven agent should be structurally blind to hidden-DOM
   payloads) but it's a second agent loop worth a day on its own — it belongs
   in the README's "Out of scope for this build" table, not in the six days.
8. **No region/proxy runs.** Proxies aren't on Free and cost $1/GB on Starter.
   Not worth it here.

## Account status

- API key at `console.getsolari.com` — I'll provide `SOLARI_API_KEY` as an env
  var; ask me for it if it's not already in your environment when you need it.
- I have a **$30 credit grant**, applied via work-email signup.
- **Credit is not the constraint — check the plan tier before you build Day 4's
  fan-out.** A $30 balance doesn't lift concurrency or session-time limits;
  those are tier features (see the plan's Budget section). If the console shows
  Free tier, a ~90-run matrix pass at 3-way browser concurrency takes about an
  hour, and Free caps a *session* at one hour while the target sandbox has to
  stay up the whole pass — you'll race that cap. If so, use the plan's fallback:
  three passes of one model each, `revert("warm")` between passes, each pass
  under the cap. Tell me what tier the console shows before you commit to a
  fan-out shape.

## Verified API surface (checked against docs.getsolari.com and the cookbook on
2026-09-02 — re-verify anything below if it doesn't match what you see, the SDK
is five weeks old and could have moved)

```ts
// Sandbox + port preview (TypeScript, from examples/sandbox-port-preview-ts)
import { SolariClient } from "@solarisdk/sdk"
const pt = new SolariClient({ apiKey: process.env.SOLARI_API_KEY! })
const sandbox = await pt.sandboxes.create({ template: "base", timeoutMs: 5*60_000 })
await sandbox.connect()
await sandbox.files.write("/tmp/site/index.html", "...")
await sandbox.commands.run("sh", { args: ["-c", "cd /tmp/site && nohup python3 -m http.server 3000 &"] })
const { url } = await sandbox.previewUrl(3000)   // → *.preview.getsolari.com
await sandbox.kill()   // NOT close() — close() only drops the local control channel

// Snapshot / revert (TypeScript only in the published docs — no Python example exists)
const snapId = await sbx.snapshot("after-setup")
await sbx.revert(snapId)
```

```python
# Browser + recording (Python, from examples/browser-session-recording-py)
from solari_browser import Solari
solari = Solari(api_key=os.environ["SOLARI_API_KEY"])
browser = await solari.launch(recording=True)   # opt-in PER SESSION, no account switch
...
blob = await solari.sessions.download_replay(browser.id)   # already-decompressed rrweb NDJSON
```

**One real unknown, resolve it on Day 0 before anything else:** does
`solari_sandbox` (Python) expose a `previewUrl`-equivalent? The PyPI page
mentions "ports" in its feature blurb but publishes no port API, and no Python
snapshot example exists despite Python being documented at full parity with
TypeScript. If Python can't do port preview or snapshot/revert, either drive
just the sandbox lifecycle from a small TypeScript shim (a session created in
one language can reportedly be driven from another) or move the whole runner to
TypeScript. Decide this first — it changes the repo layout.

Other confirmed gotchas: sandbox `commands.run` is not shell-interpreted (pass
`args`, or invoke `sh -c` yourself); backgrounding a server needs `&` inside
`sh -c` or `commands.run` blocks until idle timeout; `timeoutMs` is a rolling
idle window, not a hard deadline; TypeScript clients need `await solari.close()`
or the process hangs.

## How I want you to work

1. **Start with Day 0 from `mirage-6-day-plan.md`, literally.** Verify the
   account/tier, verify `browser-quickstart-py` and `sandbox-port-preview-ts`
   run for real, resolve the Python port-preview/snapshot question above.
   Report what you find before writing any product code — some of Day 1-6 may
   need adjusting based on what Day 0 turns up, and that's expected.
2. **Use the plan's day boundaries as checkpoints, not a script to blast
   through.** Check in with me at the end of each day's "Done when" criteria
   rather than building straight through six days unsupervised — this is a real
   week of work, not a script.
3. **Follow the repo layout in the plan's "Repo layout" section.**
4. **Keep the budget guardrails live from the first line of runner code:** hard
   step cap (~15) per agent run, `kill()` in `try/finally` on every sandbox and
   browser session, cheap model for the bulk matrix. Write
   `results/spend.json` incrementally as runs happen, not as an afterthought on
   Day 5.
5. **The README and the plan are living documents.** Update the plan's `[rev]`
   log and the README's `FILL` markers as you actually produce the things they
   describe — don't let them drift from what's true.
6. Ask me before: spending real money beyond the $30 grant, emailing
   `hello@getsolari.com`, posting anything publicly, or opening the cookbook PR.
   Everything else — writing code, running the local backend, running against
   Solari within budget, committing to git locally — go ahead without asking.

Start by reading `mirage-6-day-plan.md` and `README.md` in full, then begin
Day 0.
