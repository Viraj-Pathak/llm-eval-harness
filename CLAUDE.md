# CLAUDE.md — working notes for Claude Code

This file orients you (Claude) when continuing work on this repo. Read it first.

## What this project is

A provider-agnostic LLM evaluation harness with a CI regression gate. It already runs
end to end against a deterministic `mock` provider (so `make eval`, `make gate`, and
`pytest` all pass with zero API keys). The architecture is intentionally small and
typed; keep it that way.

## Current state (working)

- `llm_eval/config.py` — dataclass config for suites, tasks, scorers; `.jsonl` loader.
- `llm_eval/clients.py` — `ModelClient` interface; `MockClient` (offline, deterministic)
  plus `AnthropicClient` / `OpenAIClient` (lazy imports). Returns token usage + latency.
- `llm_eval/scorers.py` — `Scorer` base + registry. Implemented: `exact_match`,
  `contains`, `regex`, `json_schema`, `llm_judge`, `groundedness`.
- `llm_eval/runner.py` — runs a suite, aggregates weighted scores, records p50/p95 + cost.
- `llm_eval/report.py` — markdown report + `compare_to_baseline` (drives the gate).
- `llm_eval/__main__.py` — CLI: `run`, `baseline`, `gate`.
- `suites/summarize.json`, `datasets/`, `prompts/` — a working example suite.
- `tests/test_scorers.py` — 5 passing unit tests.
- `.github/workflows/eval.yml` — CI: tests + `gate` on every PR.

Run `make test && make eval` to confirm green before changing anything.

## Conventions

- Python 3.10+, standard library first. Only hard dep is `jsonschema`; provider SDKs are
  optional extras and lazy-imported. Don't add heavy deps without reason.
- Scorers return `ScoreResult(score in [0,1], detail)`. Always set a useful `detail` so
  failures are debuggable from the report.
- Everything reproducible from config + dataset. No hidden global state.
- `temperature=0.0` for judges. Pin judge model/version in the suite.

## Build-out roadmap (pick up here, roughly in order)

1. **HTML dashboard.** Add `llm_eval/dashboard.py` that renders a run (or a baseline-vs-current
   diff) to a self-contained `report.html` — per-scorer bars, per-case table with outputs
   and judge reasons, latency/cost summary. No framework; inline CSS. Add a `dashboard`
   CLI subcommand and a `make report` target.
2. **Per-slice breakdown.** Use `case.metadata` (e.g. `domain`) to report scores by slice,
   so regressions in one segment aren't hidden by the average.
3. **More scorers.** `semantic_similarity` (embedding cosine vs reference), `latency_budget`
   (pass if p95 under a threshold), `cost_budget`, `toxicity`/safety via a judge rubric.
4. **Multi-model sweep.** A `sweep` command that runs the same suite across several
   models/prompts and prints a comparison table — the artifact recruiters actually want to see.
5. **Real pricing table.** Fill `PRICE_PER_MTOK` in `clients.py` for the models you use,
   with a comment noting the date checked (pricing drifts).
6. **A second, harder dataset.** Add a domain dataset with adversarial cases (ambiguous
   inputs, ones that tempt hallucination) so the groundedness scorer earns its keep.
7. **Caching.** Cache `(prompt, model, temperature)` -> completion to disk so re-runs and
   judge calls don't re-bill. Key by hash; store under `.cache/`.

## Things to NOT do

- Don't break the offline mock path — CI depends on it.
- Don't hardcode model strings or prices as facts; make them config and date-comment them.
- Don't turn this into a notebook. The whole point is that it's a testable, gated package.

## Stretch (portfolio polish)

- Publish the dashboard for the example suite to GitHub Pages from CI.
- Write a short `WRITEUP.md`: the problem (silent LLM regressions), the design choices
  (deterministic vs judge, baseline+tolerance gating), and one real before/after where a
  prompt change moved the numbers. That narrative is what turns this repo into interviews.
