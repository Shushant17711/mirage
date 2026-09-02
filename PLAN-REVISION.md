# Mirage — plan revision after verifying Solari's actual API and pricing

Verified 2026-09-02 against docs.getsolari.com, the cookbook repo, and PyPI.
This supersedes the assumptions in `mirage-6-day-plan.md`. Nothing here is
inferred from the old plan; each item cites what was checked.

---

## 0. State of the repo

`/home/shushant/Projects/Solari` contains two markdown files and no code.
Day 0 has not started.

**The README is written in past tense about software that does not exist.** It
says "The local backend, target sites, and grader work end to end." That is
currently false. The status banner softens it but does not fix it. Do not
publish this file until each claim in it is true. Rewrite it as a spec now, or
delete it and write it on Day 5 from real output.

---

## 1. Verified API surface

From `examples/sandbox-port-preview-ts/index.ts` in the cookbook:

```ts
import { SolariClient } from "@solarisdk/sdk"
const pt = new SolariClient({ apiKey: process.env.SOLARI_API_KEY! })

const sandbox = await pt.sandboxes.create({ template: "base", timeoutMs: 5*60_000 })
await sandbox.connect()
await sandbox.files.write("/tmp/site/index.html", "...")
await sandbox.commands.run("sh", { args: ["-c", "cd /tmp/site && nohup python3 -m http.server 3000 &"] })
const { url } = await sandbox.previewUrl(3000)   // -> *.preview.getsolari.com
await sandbox.kill()
```

From docs.getsolari.com/snapshots (TypeScript only — no Python shown):

```ts
const snapId = await sbx.snapshot("after-setup")   // machine keeps running
await sbx.revert(snapId)                           // same sandboxId, state rewound
await sandboxes.create({ template: "base", fromSnapshot: snapId })  // independent copy
await sbx.pause() / await sbx.resume()
```

The docs never use the word "fork." The mechanism is `fromSnapshot` on create.
Python is documented as at **full parity** with TypeScript for snapshots
(docs.getsolari.com/languages), but no Python snapshot example is published
anywhere. Budget Day 0 time to derive it.

Browser (Python, `solari_browser`):
```python
solari = Solari(api_key=...)
browser = await solari.launch(recording=True)   # opt-in per session, no account switch
blob = await solari.sessions.download_replay(browser.id)
```

---

## 2. The three findings that break the old plan

### 2.1 Sandbox concurrency makes the "parallel fan-out" headline impossible

| Plan | Concurrent sandboxes | Concurrent browsers |
|---|---|---|
| Free ($0, $3 credits/mo) | **1** | 3 |
| Starter ($20) | **2** | 20 |
| Professional ($200) | 10 | 150 |

The old plan's headline was "fork per cell, concurrency cap 4–6, time serial vs
parallel." You cannot run 4–6 concurrent sandboxes below the $200 tier. On
Starter you get two.

**Browsers are the cheap, plentiful resource: 20 concurrent on Starter.** The
fan-out belongs on browser sessions, not sandboxes — which is also the correct
architecture, see 2.2.

### 2.2 Fork-per-cell is solving a problem this design does not have

The target is a Flask app that renders deterministically from `?variant=`. It is
stateless. Byte-identical state across cells is therefore already guaranteed by
the app being stateless — a snapshot fork buys nothing over an HTTP query
parameter. The old plan calls this "the load-bearing primitive." It isn't, and
that is exactly the kind of thing an interviewer pulls on.

Snapshot/revert becomes genuinely load-bearing only if the target has **mutable
state the agent can modify** — a webmail outbox that really accumulates sent
mail, a ticket queue the agent posts into, a cart. Then "reset the world between
runs" is a real requirement.

So: **make the targets statefully mutable on purpose.** That is a design change,
not a workaround, and it makes the whole benchmark more realistic — an agent
that can actually send mail is an agent whose unauthorised actions mean
something.

### 2.3 Published replay links will be dead before anyone clicks them

Replay retention: **Free 1 day, Starter 7 days**, Professional 30. A README that
links to Solari replay endpoints will 404 for every reader who arrives in week
two.

The fix is better than the problem. Replays are **rrweb NDJSON, gzipped**, and
the HTTP client already decompresses them — so a replay is a small, greppable,
diffable text file. Download every replay, commit it to the repo, and ship a
static rrweb player page. Permanent, self-hosted, reproducible evidence that
outlives the retention window. Almost nobody else will do this.

---

## 3. Revised architecture

```
  runner (laptop)
     │
     ├── 1 sandbox ── Flask targets, stateful, state namespaced by run_id
     │      ├── previewUrl(3000) -> https://<id>.preview.getsolari.com
     │      └── snapshot("warm") once, app booted and healthy
     │
     ├── N concurrent browser sessions (8-16; cap 20 on Starter)
     │      recording=True, each one cell, ?variant=..&run_id=..
     │
     ├── GET /events?run_id=  -> server-side ground truth per run
     ├── download_replay(session_id) -> commit the NDJSON
     └── revert("warm") between full matrix passes -> clean world per pass
```

**Isolation story, stated honestly:** within a pass, runs are isolated by
`run_id` namespacing. Between passes, `revert(warm)` restores the machine.

**And then validate that claim.** Re-run a sample of cells the expensive way —
serial, `revert(warm)` before every single run, true byte-identical machine
state — and show the outcomes match the namespaced runs. That converts
"isolation by namespacing" from an assumption into a measured result, and it
uses snapshot/revert as something genuinely load-bearing. This validation
control is the strongest methodological move available in this project.

---

## 4. Real cost (the old plan's budget guardrails were aimed at the wrong risk)

Starter, $20/mo:
- Browser $0.10/hr. A ~2-minute run costs **$0.0033**.
- 12 cells x 3 runs x 2 models + ~18 controls ≈ 90 runs ≈ **$0.30**.
- Sandbox 1 vCPU / 2 GB = $0.057/hr. 40 hours across the week ≈ **$2.28**.

**Total Solari spend for the whole week: under $5.** Solari is not the budget
risk. LLM tokens are — a looping agent burning context is what costs money, so
the hard step cap (~15) matters and the credit-anxiety in the old plan does not.

Free tier ($3/mo credits) is enough to build on and probably enough to finish.
Starter's real value is 20 concurrent browsers and 7-day replay retention.

---

## 5. Cut these

- **Regions / geographic egress.** Free tier has no proxies at all; Starter
  charges $1.00/GB. The docs have a /regions page but list no region
  identifiers. Not worth a day.
- **Desktop / VNC.** Nothing in this project needs a screen.
- **The parallel-vs-serial speedup as the headline.** It is an infra benchmark
  on the vendor's own product, run by someone applying to that vendor. It reads
  as flattery and it is unfalsifiable from outside. Keep the timing as a
  footnote if you like; do not lead with it.

## 6. The headline should be a finding, not an infra number

Lead with something only this project can say. Candidates:

- Compromise rate by **surface**: hidden DOM vs visible text vs embedded frame.
  If hidden-DOM payloads land at a materially different rate, that is a concrete,
  quotable, actionable result.
- The **resistance-vs-utility frontier**. This is the one genuinely novel idea in
  the original plan and it survives review intact. Everyone measures resistance;
  measuring whether a hardened agent becomes too paranoid to finish benign work
  is the chart nobody has. Keep it. It is your differentiator.

---

## 7. Positioning (matters more than it looks)

`solari-sandbox` on PyPI is maintained by **`pinetreeresearch`** — the company
hiring. The cookbook's client variable is `pt`. Solari is Pinetree's product and
this challenge is a dogfooding funnel.

That has a consequence for framing. A submission whose thesis is "browser agents
are dangerously insecure" is one inference away from "your customers' products
are broken." Same data, better frame:

> **If you are building a browser agent on Solari, this is how you test it
> before you ship it.**

Complementary asset, not indictment. Say that in the README's first paragraph.

---

## 8. Where the SDK's age is your opportunity

`solari-sandbox` is **v0.2.0, published 2026-07-27** — about five weeks old.
Documentation gaps are real and findable, and for a project this young, good DX
feedback is worth more to them than another demo. Verified gaps as of today:

1. **No Python port-preview example.** `sandbox-port-preview-ts` exists;
   there is no `-py` counterpart, and your project is Python. This is the
   cookbook PR: `sandbox-port-preview-py`, matching house style — module
   docstring that leads with the gotcha, `try/finally`, a comment at the exact
   line where the trap bites.
2. **No Python snapshot example anywhere**, despite Python being documented at
   full parity. The /snapshots page is TypeScript-only.
3. **Package naming is already inconsistent.** Docs say `@solarisdk/sandbox`;
   the cookbook example imports `SolariClient` from `@solarisdk/sdk`. The Rust
   crate `solari-sandbox` collides with the Python package name. Browser and
   desktop both export a class called `Solari`.
4. **Replay retention is not mentioned in the recording docs or example** — only
   on the pricing page. Anyone building a report with replay links hits this
   cold. That is a one-line docs fix and a genuinely useful thing to report.

Send these as a short, unemotional DX note. Not a complaint list — an
observations list from someone who used the thing hard for a week.

---

## 9. What the competition will submit

Most entries will be one primitive used shallowly: a stealth scraper, a
form-filling agent, a "book me a flight" demo, a computer-use screenshot loop.
They will have a video, a README with adjectives, and no artifacts.

Beat that on things that are cheap for you and expensive for them:

| Move | Why it wins |
|---|---|
| Committed `results.jsonl` | Raw output anyone can re-derive. Adjectives don't survive next to data. |
| Committed rrweb replays + static player | Permanent evidence. Outlives their retention window. Nobody will think of it. |
| The validation control (§3) | Turns a methodological assumption into a measurement. |
| An honest limitations section | Rare, and the single clearest judgment signal available. |
| A small merged cookbook PR | You contributed to their repo before they hired you. |
| The DX note | Five-week-old SDK. This is what they actually need. |

---

## 10. Revised day plan

**Day 0 (before the clock)** — key from console.getsolari.com. Run
`browser-quickstart-py` and `sandbox-port-preview-ts` verbatim. **Derive the
Python snapshot/revert calls and confirm `previewUrl` exists in
`solari_sandbox`** — this is the one unverified dependency left; if
`previewUrl` is TS-only, either drive the sandbox from a small TS shim (the
docs note a session created in one language can be driven from another) or move
the runner to TS. Confirm `recording=True` then poll ~30s for the replay.

**Day 1** — Flask targets, stateful, `run_id`-namespaced. `/canary`,
`/honeypot/<action>`, `/events`. Serve inside the sandbox via `previewUrl`.
Done when you can open the fake support portal in Chrome on a public URL and a
honeypot click lands in `/events`.

**Day 2** — Minimal agent loop, 5 tools, 15-step hard cap. One green run on
`?variant=clean`, replay downloaded and watched. Measure cost per run.
This is the time sink. If it is still broken end of Day 3, cut to one site.

**Day 3** — 12 payloads (S1–S3 x I1–I4). Serial matrix, x1, one model.
First ugly honest table.

**Day 4** — Browser-level fan-out at 8-16 concurrent. `snapshot("warm")` +
`revert` between passes. **Run the validation control on a sample of cells.**
Second model, 3 runs per cell, control runs for the utility axis.

**Day 5** — `report.html`: matrix, both metrics, the resistance-vs-utility
scatter, committed replay per cell via the static player. README written from
real output, in this order: video, the finding, the problem, why ordinary infra
can't do this, architecture, 3-command quickstart, results, **limitations**,
ethics. `AGENTS.md` on how you drove the build with AI. Atomic commits. Open
the cookbook PR.

**Day 6** — 75-90s screen recording: public URL loads, matrix runs, an agent
gets compromised on replay, scorecard. Post video-first. Tag `@harrychow_` and
`@getsolari` on both platforms. Send the DX note. DM Harry: one line, the
finding, the link, and ask eligibility questions there.

---

## 11. Keep from the original plan

These were right and survive review unchanged:

- Server-side grading, never an LLM judge. The target app owns the truth.
- Unique canary tokens per run rather than string-matching agent output.
- Self-hosted targets and self-run agents only. No third-party services.
- Generic, publicly-documented payloads — measurement, not attack development.
- 3 runs per cell; report a rate, not a binary.
- The resistance-vs-utility axis. This is the idea worth having.
- The limitations section as a deliverable in its own right.
