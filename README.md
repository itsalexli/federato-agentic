# AI Underwriting Agent

Hack the North 2026 · Federato API Challenge

An agent that triages a commercial insurance submission queue: it discovers the data
model at runtime, works out which queries answer the carrier's appetite guidelines,
scores and ranks every submission, and explains each decision in language an
underwriter can act on.

```bash
cp .env.example .env          # add your client_id / client_secret
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python -m app.cli --verbose --trace
```

---

## The problem this solves

The appetite table scores on TIV, construction type, building year, premium, primary
risk state and five-year loss history. A `Submission` record carries none of them:

```
Submission
  id, status, line_of_business, requested_limit, received_date
  broker -> Broker      insured -> Insured      underwriter -> Underwriter
```

Worse, the 21 submissions actually sitting open in the queue — `received`, `cleared`,
`quoted` — have **no linked policy at all**. `Policy.submission` points back at them,
and only the 113 already-bound ones are on the other end of it. So there is no policy
to read a premium or an exposure schedule from.

The route that works is the one a real underwriter takes on new business: work the
**account**, not the piece of paper. From `Submission.insured` the agent reaches the
insured's HQ location, the locations and buildings on its prior policies, and its
claim history — and scores the submission on the footprint the account actually has.

```
Submission -> Insured -> hq -> Location -> Building        TIV, construction, year built
           -> Insured <- Policy -> exposure_units -> Location -> Building
                              -> premium on the expiring same-line term
                              -> claims -> Claim                five-year loss history
```

## How the agent works

```
discover schema  ->  locate each appetite rule's data  ->  plan queries
      ->  execute (adapting on failure)  ->  assemble dossiers  ->  score
      ->  enrich  ->  explain  ->  rank
```

Asking it a question runs a different loop over the same machinery: the model plans the
queries instead of the rules doing it. See [Asking it questions](#asking-it-questions).

Every stage writes to a shared trace, so the ranking can be read backwards to the
queries that produced it. `--trace` on the CLI, or the **?** button beside the tabs in
the UI.

### It derives its joins rather than hardcoding them

The agent never contains a written-out path from Policy to Building. It searches the
discovered schema for the field that holds the number it needs, then asks for a route:

```python
schema.paths_between("Policy", "Building")
# [['insured', 'hq', 'buildings'],
#  ['exposure_units', 'location', 'buildings']]
```

Both routes are three hops and **they reach different buildings**, so taking whichever
one a breadth-first search found first would silently drop half an account's footprint.
The planner keeps every minimal route and merges them into one `expand` stage:

```json
{"expand": {"insured":        {"hq":       {"buildings": true}},
            "exposure_units": {"location": {"buildings": true}}}}
```

### It adapts when a query comes back wrong

| What happens | What the agent does |
|---|---|
| Query validates, returns 0 rows | Retries against a pre-planned broader filter, recording why |
| `[VALIDATION_ERROR]` on an array dot-path | Rewrites it as `$elemMatch` from the schema and retries |
| `[VALIDATION_ERROR]` on an unknown field | Drops that one clause rather than losing the whole result set |
| Token expires mid-run | Re-mints once and replays the request |
| Open-Meteo rate-limits or fails | Backs off, then continues without enrichment and says so in the trace |

### It costs a fixed number of queries

Triaging 21 submissions takes **6–7 API calls**, not one per row: the queue comes back
in one query, then accounts, policies, claims, brokers and underwriters are each fetched
in a single bulk `$in`. The same shape handles the full 158-submission queue.

## Scoring

The 2025 commercial property table, as weighted data in [`appetite.py`](backend/app/agent/appetite.py).
The API serves the same objects to the UI's **Guidelines** tab, so the documentation
cannot drift from the scoring.

| Factor | Weight | Hard stop |
|---|---|---|
| Line of business | 20 | yes |
| Primary risk state | 18 | yes |
| Total insured value | 16 | |
| Total premium | 14 | |
| 5-year loss history | 12 | |
| Construction type | 10 | |
| Building age | 6 | |
| Submission type | 4 | |

Target scores full weight, acceptable 60%, unacceptable 0.

### Judgment calls, and why

**A hard stop caps the score at 25 instead of zeroing it.** An out-of-footprint account
that is otherwise excellent is a broker conversation or a filing question, not a
nothing — and it must still outrank a genuinely bad risk. Zeroing would flatten that
distinction and hide it.

**Missing data grades `unknown` at 30% of weight, not 0%.** Penalising an unworked
submission as though it were a bad risk would bury every genuinely new account in the
queue. Each scorecard carries a **confidence** figure — the share of scoring weight
backed by observed data — and anything under 55% is recommended for
*request information* rather than a decision.

**Loss history is scoped to the line being underwritten.** A medical group with $4.8M of
health claims and a clean property record is not a $4.8M property risk. When the account
has written the same line before, only that line's losses are scored; the account-wide
figure is carried alongside and disclosed in the note.

**Loss means incurred, not paid.** Paid plus outstanding reserves. Scoring paid alone
would flatter an account whose large claims are still open — exactly the account you
most want flagged.

**Premium on an unquoted submission is indicative.** There is no premium to read, so the
most recent expiring term on the same line is scored, labelled `indicative` everywhere
it appears so nobody mistakes it for a quote.

**Construction is weighted by insured value, not building count.** The guideline says
">50% JM, non-combustible or masonry non-combustible". Ten sheds and one steel warehouse
is not a frame risk.

**Fire Resistive is graded acceptable although the table doesn't name it.** It outranks
every class the table does name on the standard ISO ladder, so reading it as unacceptable
would invert the rule's intent. The explanation says so explicitly wherever it applies.

**Primary risk state is the state carrying the most insured value**, not a majority of
addresses — the exposure is what's being rated.

## Asking it questions

The scoring engine is deterministic by design. The *query planning* is where a model
belongs, and `--ask` is where it sits:

```bash
cd backend
../.venv/bin/python -m app.cli --ask "which open property submissions are in CA with clean losses?"
```

The model is handed the schema the agent discovered at runtime, the query language, and the
appetite table. It then plans: writes a query payload, sees what comes back, and decides
whether to refine, widen, follow a reference, or answer. Two tools:

| Tool | What it does |
|---|---|
| `run_query` | Any read-only query payload, executed through the agent's own adaptive runner |
| `score_submissions` | Hands a slice of the queue to the deterministic scorer |

The division is deliberate. **The model chooses what to ask; the scoring engine decides
what a submission is worth.** Appetite judgement is never improvised — the model is told
to call `score_submissions` rather than grade by hand, so a score is reproducible no
matter what the model does on any given run.

Its queries get the same safety rails as everything else. A field path is validated
against the schema before a round trip is spent; a dot-path through an array is rewritten
as `$elemMatch`; an unknown clause is dropped rather than failing the turn; an error comes
back as feedback the model can correct from. Rows returned to the model are capped at 20,
but `total` is always exact, so counts never come from a truncated list. Every query it
writes — and the reason it gave — lands in the same reasoning trace as the rest of the run.

Without `ANTHROPIC_API_KEY` this one feature is unavailable and says so; everything else
runs unchanged.

## Explanations

Every submission gets three sentences: what drove the score, the material counterweight,
and the recommendation with a next action. Both writers are generated **from the
scorecard**, not from the raw record, so a note can only cite a factor that was actually
evaluated.

- **Deterministic** — always runs, needs no key, and is what the tests assert against.
- **Model-written** — when `ANTHROPIC_API_KEY` is set, the model rewrites the top of the queue in better
  prose from the same scorecard. Any failure or timeout falls back to the deterministic
  text and the run reports which wrote what.

Contradictions are stated rather than smoothed over. A submission that targets on line
and state but fails on losses and building age says exactly that.

## External enrichment (bonus)

Hazard tags say a site is exposed; they don't say how hard it has been hit.
[Open-Meteo's ERA5 archive](https://open-meteo.com/) is free and keyless, so the agent
pulls five years of daily precipitation and wind gusts at each account's **largest**
location and counts the days over 50mm of rain or 90km/h gusts.

The result moves the score by at most ±5 points — enough to break ties between
comparable risks, not enough to overturn the carrier's own table. Base and adjusted
scores are both shown, and the note states the adjustment and its reason. Results are
cached to disk; failures are logged to the trace and the run continues.

## Running it

The **Dataset** tab carries the field notes on what the API actually returns — every
figure hover-reveals the evidence behind it and what it forced in the agent.

Pressing **Tab twice** (or ⌘K) unfolds a chat out of the cursor, anchored where the
pointer is rather than centred over the page. It answers questions about the run on
screen — why a submission scored what it did, which queries produced the ranking, what is
a rule versus what a model wrote — by reading the run's own trace and scorecards rather
than querying the API again. A single Tab is never swallowed, so keyboard navigation is
unaffected.

**API + dashboard**

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000 --app-dir backend
npm install --prefix frontend && npm run dev --prefix frontend   # http://localhost:5273
```

**CLI**

```bash
cd backend
../.venv/bin/python -m app.cli                      # rank the open queue
../.venv/bin/python -m app.cli --verbose            # full factor breakdowns
../.venv/bin/python -m app.cli --trace              # the agent's reasoning
../.venv/bin/python -m app.cli --all --lob property # include bound/declined/lost
../.venv/bin/python -m app.cli --json out.json      # machine-readable export
../.venv/bin/python -m app.cli --ask "..."          # ask a question in English
```

**Tests** — 95 of them; the live ones skip themselves without credentials, and the
query loop is exercised against a stubbed model.

```bash
.venv/bin/python -m pytest backend/tests -q
```

## Endpoints

| Route | Returns |
|---|---|
| `POST /api/ask` | Answer a question by planning and running queries |
| `POST /api/how` | Explain how the agent produced what is on screen |
| `GET /api/triage` | Ranked queue with scorecards, explanations and the full trace |
| `GET /api/submissions/{id}` | One submission's scorecard |
| `GET /api/guidelines` | The appetite table as the scorer applies it |
| `GET /api/schema` | The discovered data model |
| `GET /api/health` | Whether LLM notes and enrichment are on |

Query params on `/api/triage`: `status` (repeatable), `line_of_business`, `enrich`,
`llm`, `refresh`.

## Layout

```
backend/app/
  config.py              env and endpoints
  federato/
    client.py            auth, token cache, transport, typed error parsing
    schema.py            runtime discovery, path validation, route finding
  agent/
    appetite.py          the guidelines as weighted data + the scorer
    ask.py               natural-language query loop -- the model plans, tools execute
    meta.py              answers questions about the run itself, from its own trace
    planner.py           locates data in the schema, plans and adapts queries
    dossier.py           folds hydrated records into one dict per submission
    enrich.py            Open-Meteo severe-weather history
    explain.py           deterministic and model-written explanations
    pipeline.py          the loop that ties it together
    trace.py             the reasoning record
  main.py                FastAPI
  cli.py                 terminal front end
frontend/src/            React dashboard: Queue, Ask, Portfolio, Guidelines, Dataset
  styles.css             Federato's design tokens, applied dark
                         (the reasoning trace opens from the ? button in the tab row)
backend/tests/           95 tests; live ones skip without credentials
```

## Design

The dashboard uses Federato's own system, read off federato.ai rather than approximated.
It runs as three full-bleed sections. A hero carrying Federato's aerial field plate, a
distinct band for the run's figures and navigation, then a rule spanning the whole screen
with the working views below it:

| | Dark sections (above the rule) | Light band (below it) |
|---|---|---|
| Ground | maroon `#1a1210` | grey `#f7f7e3` |
| Surface | `#231917` | pale card `#f9eec6` |
| Text | grey `#f7f7e3` | meridian maroon `#2d1d1a` |
| Accent | beacon teal `#47fac4` | atlas green, darkened to `#3f8f4d` to read on cream |

Identity sits over the field plate, the headline figures get their own section beneath it,
and every working view sits in the light band. Only the role tokens are redefined on
`.band-light`, so each component follows without a second set of rules.

The pointer follows the same split: beacon teal over the dark sections, grounded brown
`#a66b42` over the cream, so it always has contrast against what it is sitting on. The
command palette is frosted cream rather than tinted, and carries the light token set so
its contents stay legible over either band.

Shared: type at weight 300 with `-0.02em` tracking and 1.3 leading; radii 8px and 20px;
pill buttons; semantic colour from their own swatches (atlas green, lumen yellow, sigal
orange).

Submissions that are in appetite fill with a pale atlas green from the bottom edge under a
fine crosshatch — the treatment Federato gives the levels past the AI-native gate in their
own diagrams, so importance reads as a rising wash rather than another badge.

Their body face is **Case** and their display face is **Reckless Standard M**. Both are
licensed and cannot be served here, so **Hanken Grotesk** and **Newsreader** stand in —
same roles, same weights, same tracking. Their site also lays a repeating noise plate over
the page at `mix-blend-mode: soft-light`; that is reproduced with an inline `feTurbulence`
texture so nothing extra is fetched.

## Notes on the API

- The auth tenant is `auth.product.federato.ai`, not the product domain. Minting against
  the product domain returns a token the API rejects with 401.
- `?outputOnly=true` is documented to strip the workflow envelope but responses still
  arrive as `{"output": [{"data": ...}]}`. The client unwraps defensively.
- Errors arrive as plain strings with the code inline — `[VALIDATION_ERROR] ... {...}` —
  so `FederatoError` parses the prefix back out to make it branchable.
- **`over` does not collapse groups on this deployment.** `id` stays in the partition
  key regardless of what you pass, so every "group" comes back as a single row. The
  agent detects this at runtime (rows == total), recomputes the rollup client-side, and
  records the fallback in its trace rather than reporting wrong numbers.
