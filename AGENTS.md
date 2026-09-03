# AGENTS.md

How this repo was actually built, since the challenge asked for it explicitly.

## Setup

The whole project was built inside a single extended Claude Code session,
driven from a build prompt (preserved in `START-HERE.md`) written before any
code existed. That prompt did the work a human engineer would normally do
before opening an editor: it named the architecture decisions already made
and why, listed the verified API surface as of the SDK's actual version,
flagged the one real unknown to resolve first, and set explicit checkpoints
— "check in with me at the end of each day's Done-when criteria rather than
building straight through six days unsupervised."

That last instruction mattered more than any other. This was not a
"write me an app" prompt executed once. It was six work sessions, each
starting from the previous day's actual state, each ending with a report of
what was found and a question when something needed a human call.

## What the agent actually did, day by day

**Day 0.** Cloned the real cookbook, installed the real SDK, and ran the
quickstart examples against a live account before writing a line of product
code. This is where the plan's stated "one real unknown" (does the Python
SDK support `previewUrl`?) got resolved by reading the installed package's
source directly — `dir()` on the class didn't show `sandbox.files` and
`sandbox.commands` because they're instance attributes set in `__init__`,
not class attributes, which cost some confusion before finding the actual
`SessionHandle` base class. It also found something the plan didn't
anticipate: `sandbox.revert(snapshot_id)` fails with an undocumented
`409 Not revertable` on a completely fresh sandbox, immediately after a
successful `snapshot()`, regardless of pause state or snapshot lineage —
confirmed across six separate live tests before accepting it as a real
product limitation rather than a usage error, and adopting
`create(from_snapshot=...)` + `kill()` as the workaround for the rest of
the project.

**Day 1.** Built the Flask targets and got one honeypot hit logged through
a real public `previewUrl`, verified with an actual browser screenshot once
the Claude-in-Chrome extension was connected (it initially wasn't, and no
guess was made about what that screenshot would show while waiting for it).

**Day 2 — the day estimated to be the biggest time sink, and it was, for
different reasons than expected.** The tool loop itself came together fast.
What took the time was chasing why replays were silently coming back empty.
That turned into a genuine investigation: a sync HTTP client blocking the
event loop and starving the browser session's keepalives (fixed by
switching to `AsyncOpenAI`), and then — after that fix didn't solve it —
four separate isolated tests establishing that Solari's own
`recording=True` session replay simply does not work once the browser
visits the sandbox's own `previewUrl` domain, independent of the auth
token or session length. That is not a documented limitation anywhere.
Rather than treat it as a blocker, the response was to self-host rrweb
capture in the target pages instead — same output format, no dependency on
the broken feature. This is the kind of finding a prompt can't anticipate;
it only came from actually running the thing against the real account,
repeatedly, with instrumentation, until the failure was reproducible on
demand instead of just "sometimes doesn't work."

**Day 3.** Wrote the 12-cell corpus, and before trusting the first
matrix pass, checked whether the agent's own `read_page()` tool could
even see the payloads it was supposed to be tested against. It couldn't:
`innerText` respects CSS rendering and silently drops `display:none` text,
so the hidden-DOM and iframe surfaces were structurally invisible to the
agent regardless of model behavior — which would have produced a "perfect
resistance" result that was actually a tool bug wearing a lab coat. Fixed
before running anything real, not after.

**Day 4.** Ran the full matrix, found a second live bug the same way (a
transient 503 crashing the isolation control mid-run, discarding several
already-completed and expensive VM-reset runs because results were only
returned at the end rather than reported incrementally), fixed it, and
then made a judgment call worth naming explicitly: the first full matrix
came back at 100% resistance for both models. Rather than write that up as
the final finding, the call was to add a small "strong" tier using named,
public prompt-injection techniques — not to manufacture a scarier number,
but because a flat null result at this scale usually means the corpus
isn't stressing anything, and the plan's own Limitations section already
names generic payloads as "a floor, not a ceiling." That tier surfaced the
one real compromise in the whole project.

**Day 5.** Filling in the README's `FILL` markers surfaced one more gap:
the Quickstart had documented a `--backend local` path since the first
draft, and Day 2 had explicitly deferred building it. Rather than
soften the claim into vaguer prose, it got built and the documented
command was actually run before being left in the README.

## What a human did

Provided the initial architecture and constraints; chose the LLM
providers and supplied API keys; made the explicit calls on tradeoffs the
agent flagged rather than resolved unilaterally — the `revert()`-is-broken
workaround, proceeding on Free tier, which second model to test, and how
to react to the first matrix pass coming back at 100% resistance. Answered
"do you want X or Y" more than a dozen times over the course of the build.
Never wrote or edited a line of code directly.

## What this means for the numbers in this README

Every bug described above was caught before it could quietly corrupt a
result, not after — verified live against the real account rather than
assumed from documentation, several times over the course of the project,
because the documentation was wrong or missing in exactly the ways a five-
week-old SDK's documentation tends to be. That doesn't make the findings
immune to the limitations listed above; it's the reason there's a
Limitations section at all instead of just a scoreboard.
