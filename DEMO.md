# Demo script

A 2–3 minute walkthrough. The order is deliberate: it opens on the thing the
judges are scoring (reasoning), not on the dashboard.

---

## Before you hit record

```bash
.venv/Scripts/python.exe -m pytest backend/tests/test_live.py -q
```

Seven passes means auth, schema discovery and querying are all live. If it
fails, the token expired — it re-mints automatically on the next call, so just
run it again.

Then, in two terminals:

```bash
.venv/Scripts/uvicorn.exe app.main:app --port 8000 --app-dir backend
```

```bash
npm run dev --prefix frontend
```

**Warm the cache before recording.** Open http://localhost:5273 and let the
first run finish (~28s). A triage run is cached per parameter set, so on camera
the queue appears instantly instead of making you wait through a spinner.

**Know the one slow spot.** The Ask tab is live every time — a question with the
critic on takes 30–60s, because each query gets a second model call verifying
it. Either narrate over the wait, cut it in the edit, or set `CRITIC_ENABLED=0`
(you lose the best part of the demo, so prefer cutting).

---

## The script

### 0:00–0:20 · The problem

> "An underwriter opens their queue and sees 21 submissions. Nothing on a
> submission record says whether it's a good risk — no TIV, no construction
> type, no loss history. Those live three or four joins away, on the account.
> This agent goes and gets them, scores the queue, and shows its work."

Land on the queue, already ranked.

### 0:20–0:50 · It ranks, and it explains

Click **#1 Merrin Hale**. Point at the underwriter note.

> "71 out of 100. Target line, target state, $61M TIV in the sweet spot — but
> $713K of incurred losses against a $100K limit, and a building from 1949.
> It says both things. It doesn't smooth the contradiction over."

Scroll to the scorecard.

> "Every factor, its weight, and why it scored what it did. Loss history is
> zero out of twelve, and it tells you the number that made it zero."

### 0:50–1:40 · The part that matters: it thinks

Hit **?** (top right of the tab row).

> "This is every query it ran, and why."

Point at step 1.

> "It doesn't hardcode where TIV lives. It searches the schema it discovered at
> runtime for the field, then derives a route to it. Policy to Building has two
> equally short paths that reach *different* buildings — it keeps both and
> merges them into one expand, because taking the first one would silently drop
> half the account's footprint."

Point at the three lanes.

> "Three actors. The planner is a model deciding what to ask. The executor is
> deterministic — it validates paths, rewrites array dot-paths as $elemMatch,
> broadens empty results, and spends no tokens doing it. The critic is a
> separate call that checks whether the result actually showed what the planner
> expected."

> "21 submissions, six API calls. Not one per row."

### 1:40–2:20 · It disagrees with itself

Go to **Ask**. Click the CA / clean-losses example.

*(While it runs, keep talking — or cut here.)*

> "The planner states a hypothesis before every query: what it expects, concrete
> enough to be wrong."

When the critic lane comes back red:

> "It expected a small non-zero set. It got zero rows. A model grading its own
> hypothesis calls that a success and moves on — that's why the critic is a
> separate call that only sees the hypothesis, the query and the result. It
> says *contradicted*, and the planner revises instead of re-running the same
> shape."

> "Expectation, outcome, verdict. You can audit the reasoning, not just read it."

### 2:20–2:40 · Close

> "Appetite scoring is deterministic — the model never grades a submission, it
> calls the scorer, so a score is reproducible whatever the model does. Five
> years of weather history at each account's largest site adjusts by at most
> five points, enough to break ties and nothing more."

> "Schema discovered at runtime, queries derived not hardcoded, every decision
> traceable back to the query that produced it."

---

## If you have 30 seconds spare

- **Guidelines tab** — the appetite table exactly as the scorer applies it, served
  from the same objects, so the docs can't drift from the scoring.
- **Portfolio tab** — the "are we already exposed here?" read.
- **Dataset tab** — the field notes on what the API actually returns, including
  the `over` aggregation quirk the agent detects and works around at runtime.
- **Tab Tab** — a command palette that answers questions about the run on screen
  from its own trace, without re-querying the API.

## Don't demo

- `--ask` on the CLI when the UI shows the same thing better.
- A cold triage run. You'll lose 28 seconds of a 150-second video.
