"""Render a run as a markdown table and diff it against a committed baseline.

`compare_to_baseline` returns (ok, lines). ok is False when the aggregate score
drops by more than the suite's tolerance OR any scorer regresses materially — that
return value is what the CLI turns into a non-zero exit code to gate CI.
"""

from __future__ import annotations

from typing import Any


def to_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"## Eval: {result['suite']}",
        "",
        f"- model: `{result['task']['provider']}:{result['task']['model']}`  prompt: `{result['task']['prompt']}`",
        f"- cases: {result['n_cases']}  |  **aggregate: {result['aggregate_score']:.3f}**  |  pass rate: {result['pass_rate']:.1%}",
        f"- latency p50/p95: {result['latency_ms']['p50']}/{result['latency_ms']['p95']} ms  |  est cost: ${result['est_cost_usd']:.4f}",
        "",
        "| scorer | mean |",
        "| --- | --- |",
    ]
    for name, mean in result["scorer_means"].items():
        lines.append(f"| {name} | {mean:.3f} |")
    return "\n".join(lines)


def compare_to_baseline(result: dict[str, Any], baseline: dict[str, Any] | None) -> tuple[bool, list[str]]:
    if baseline is None:
        return True, ["No baseline found — treating this run as the new baseline."]

    tol = result.get("regression_tolerance", 0.02)
    lines: list[str] = []
    ok = True

    delta = result["aggregate_score"] - baseline.get("aggregate_score", 0.0)
    arrow = "▲" if delta >= 0 else "▼"
    lines.append(
        f"aggregate {baseline.get('aggregate_score', 0.0):.3f} -> "
        f"{result['aggregate_score']:.3f} ({arrow}{abs(delta):.3f})"
    )
    if delta < -tol:
        ok = False
        lines.append(f"  ✗ aggregate dropped more than tolerance ({tol})")

    for name, mean in result["scorer_means"].items():
        base = baseline.get("scorer_means", {}).get(name)
        if base is None:
            lines.append(f"  + new scorer {name}: {mean:.3f}")
            continue
        d = mean - base
        if d < -tol:
            ok = False
            lines.append(f"  ✗ {name} regressed {base:.3f} -> {mean:.3f}")
    return ok, lines
