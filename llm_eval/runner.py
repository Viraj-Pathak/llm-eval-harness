"""Run a suite: render prompt per case, call the model, score the output, aggregate.

Output is a plain dict (JSON-serializable) so it can be diffed against a baseline,
committed, or rendered. Each scorer contributes a weighted mean across cases; the
suite aggregate is the weighted mean of scorer means. Cases are also grouped by every
metadata key so regressions in one segment don't hide behind the overall average.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from .clients import estimate_cost_usd, make_client
from .config import Case, SuiteConfig, load_dataset
from .scorers import build_scorer


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100) * (len(s) - 1)))))
    return s[k]


def _slice_breakdown(
    cases: list[Case],
    per_case: list[dict[str, Any]],
    scorers: list[tuple[Any, Any]],
) -> dict[str, dict[str, Any]]:
    """Group per-case results by every metadata key and compute per-group means."""
    all_keys: set[str] = set()
    for c in cases:
        all_keys.update(c.metadata.keys())

    weights = {scorer.name: sc_cfg.weight for sc_cfg, scorer in scorers}
    wsum = sum(weights.values()) or 1.0

    slices: dict[str, dict[str, Any]] = {}
    for key in sorted(all_keys):
        groups: dict[str, list[dict[str, Any]]] = {}
        for i, c in enumerate(cases):
            val = str(c.metadata.get(key, "__missing__"))
            groups.setdefault(val, []).append(per_case[i])

        slice_data: dict[str, Any] = {}
        for val, group in groups.items():
            s_means: dict[str, float] = {}
            for sc_cfg, scorer in scorers:
                vals = [c["scores"][scorer.name]["score"] for c in group]
                s_means[scorer.name] = round(statistics.fmean(vals), 4) if vals else 0.0
            s_agg = round(sum(s_means[n] * w for n, w in weights.items()) / wsum, 4)
            slice_data[val] = {"n": len(group), "aggregate": s_agg, "scorer_means": s_means}
        slices[key] = slice_data

    return slices


def run_suite(
    config_path: str,
    judge_provider: str = "mock",
    judge_model: str = "mock-1",
    override_provider: str | None = None,
    override_model: str | None = None,
    override_prompt: str | None = None,
    use_cache: bool = False,
) -> dict[str, Any]:
    cfg = SuiteConfig.load(config_path)

    # Allow CLI / sweep command to override suite config at runtime
    if override_provider:
        cfg.task.provider = override_provider
    if override_model:
        cfg.task.model = override_model
    if override_prompt:
        cfg.task.prompt_path = override_prompt

    cases = load_dataset(cfg.dataset)
    template = Path(cfg.task.prompt_path).read_text()

    client = make_client(cfg.task.provider, cfg.task.model)
    judge = make_client(judge_provider, judge_model)

    if use_cache:
        from .cache import CachedClient
        client = CachedClient(client)
        judge = CachedClient(judge)

    scorers = [(sc, build_scorer(sc.type, sc.name, sc.params)) for sc in cfg.scorers]

    per_case: list[dict[str, Any]] = []
    latencies: list[float] = []
    total_cost = 0.0

    for case in cases:
        prompt = template.format(**case.input)
        comp = client.complete(
            prompt, temperature=cfg.task.temperature, max_tokens=cfg.task.max_tokens
        )
        latencies.append(comp.latency_ms)
        case_cost = estimate_cost_usd(cfg.task.model, comp.input_tokens, comp.output_tokens)
        total_cost += case_cost

        scores: dict[str, Any] = {}
        for sc_cfg, scorer in scorers:
            res = scorer.score(
                case, comp.text, judge=judge,
                latency_ms=comp.latency_ms, cost_usd=case_cost,
            )
            scores[scorer.name] = {
                "score": round(res.score, 4),
                "passed": res.score >= sc_cfg.threshold,
                "detail": res.detail,
            }
        per_case.append({
            "id": case.id,
            "output": comp.text,
            "latency_ms": round(comp.latency_ms, 2),
            "cost_usd": round(case_cost, 8),
            "scores": scores,
        })

    # Aggregate per scorer (weighted mean across cases)
    scorer_means: dict[str, float] = {}
    for sc_cfg, scorer in scorers:
        vals = [c["scores"][scorer.name]["score"] for c in per_case]
        scorer_means[scorer.name] = round(statistics.fmean(vals), 4) if vals else 0.0

    weights = {scorer.name: sc_cfg.weight for sc_cfg, scorer in scorers}
    wsum = sum(weights.values()) or 1.0
    aggregate = round(sum(scorer_means[n] * w for n, w in weights.items()) / wsum, 4)

    pass_rate = round(
        statistics.fmean(
            [1.0 if all(s["passed"] for s in c["scores"].values()) else 0.0 for c in per_case]
        ),
        4,
    ) if per_case else 0.0

    return {
        "suite": cfg.name,
        "task": {"provider": cfg.task.provider, "model": cfg.task.model, "prompt": cfg.task.prompt_path},
        "n_cases": len(cases),
        "aggregate_score": aggregate,
        "pass_rate": pass_rate,
        "scorer_means": scorer_means,
        "latency_ms": {
            "p50": round(_percentile(latencies, 50), 1),
            "p95": round(_percentile(latencies, 95), 1),
        },
        "est_cost_usd": round(total_cost, 6),
        "regression_tolerance": cfg.regression_tolerance,
        "slices": _slice_breakdown(cases, per_case, scorers),
        "cases": per_case,
    }
