"""Command line interface.

  python -m llm_eval run       suites/summarize.json                    # run + print report
  python -m llm_eval baseline  suites/summarize.json                    # save as baseline
  python -m llm_eval gate      suites/summarize.json                    # fail on regression
  python -m llm_eval dashboard suites/summarize.json [--out report.html]
  python -m llm_eval sweep     suites/summarize.json \\
        --variants mock:mock-1:prompts/v1.txt mock:mock-1:prompts/v2.txt

`gate` is what CI calls. Exit code 1 == regression beyond tolerance.
Pass --cache to persist completions to .cache/ and skip re-billing on re-runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import SuiteConfig
from .report import compare_to_baseline, to_markdown
from .runner import run_suite

RESULTS_DIR = Path("results")


def _baseline_path(config_path: str) -> Path:
    return RESULTS_DIR / f"{Path(config_path).stem}.baseline.json"


def _judge_args(args) -> dict:
    return {"judge_provider": args.judge_provider, "judge_model": args.judge_model}


def _cache_arg(args) -> dict:
    return {"use_cache": getattr(args, "cache", False)}


def _override_args(args) -> dict:
    return {
        "override_provider": getattr(args, "provider", None),
        "override_model": getattr(args, "model", None),
    }


# ── subcommands ──────────────────────────────────────────────────────────────

def cmd_run(args) -> int:
    result = run_suite(args.config, **_judge_args(args), **_cache_arg(args), **_override_args(args))
    print(to_markdown(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
    return 0


def cmd_baseline(args) -> int:
    result = run_suite(args.config, **_judge_args(args), **_cache_arg(args), **_override_args(args))
    RESULTS_DIR.mkdir(exist_ok=True)
    path = _baseline_path(args.config)
    path.write_text(json.dumps(result, indent=2))
    print(f"baseline saved -> {path}  (aggregate {result['aggregate_score']:.3f})")
    return 0


def cmd_gate(args) -> int:
    result = run_suite(args.config, **_judge_args(args), **_cache_arg(args), **_override_args(args))
    print(to_markdown(result))
    path = _baseline_path(args.config)
    baseline = json.loads(path.read_text()) if path.exists() else None
    ok, lines = compare_to_baseline(result, baseline)
    print("\n--- regression check ---")
    print("\n".join(lines))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
    if not ok:
        print("\nGATE FAILED: quality regressed beyond tolerance.", file=sys.stderr)
        return 1
    print("\nGATE PASSED.")
    return 0


def cmd_dashboard(args) -> int:
    from .dashboard import to_html

    result = run_suite(args.config, **_judge_args(args), **_cache_arg(args), **_override_args(args))
    path = _baseline_path(args.config)
    baseline = json.loads(path.read_text()) if path.exists() else None
    out = args.out or "report.html"
    Path(out).write_text(to_html(result, baseline=baseline), encoding="utf-8")
    print(f"report written -> {out}  (aggregate {result['aggregate_score']:.3f})")
    return 0


def cmd_sweep(args) -> int:
    """Run the suite across multiple model/prompt variants and print a comparison table."""
    from .dashboard import to_html

    cfg = SuiteConfig.load(args.config)
    scorer_names = [sc.name or sc.type for sc in cfg.scorers]
    headers = ["variant"] + scorer_names + ["aggregate", "pass_rate", "p95_ms", "cost_usd"]

    rows: list[list[str]] = []
    all_results: list[tuple[str, dict]] = []

    for spec in args.variants:
        parts = spec.split(":")
        provider = parts[0]
        model = parts[1] if len(parts) > 1 else cfg.task.model
        prompt = parts[2] if len(parts) > 2 else None

        result = run_suite(
            args.config,
            override_provider=provider,
            override_model=model,
            override_prompt=prompt,
            **_judge_args(args),
            **_cache_arg(args),
        )
        all_results.append((spec, result))

        row = [spec]
        for sn in scorer_names:
            row.append(f"{result['scorer_means'].get(sn, 0.0):.3f}")
        row += [
            f"{result['aggregate_score']:.3f}",
            f"{result['pass_rate']:.1%}",
            f"{result['latency_ms']['p95']:.0f}",
            f"{result['est_cost_usd']:.6f}",
        ]
        rows.append(row)

    # Print aligned comparison table
    widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    sep = "  "
    print(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print(sep.join("-" * w for w in widths))
    for row in rows:
        print(sep.join(v.ljust(widths[i]) for i, v in enumerate(row)))

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {"variants": [{"spec": s, "result": r} for s, r in all_results]},
                indent=2,
            )
        )
        print(f"\nresults written -> {args.out}")

    return 0


# ── argument parser ──────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="llm_eval")
    p.add_argument("--judge-provider", default="mock")
    p.add_argument("--judge-model", default="mock-1")
    p.add_argument("--cache", action="store_true", help="cache completions to .cache/completions/")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("run", help="run suite and print markdown report")
    sp.add_argument("config")
    sp.add_argument("--out", help="write full JSON result here")
    sp.add_argument("--provider", help="override task provider (e.g. anthropic)")
    sp.add_argument("--model", help="override task model (e.g. claude-haiku-4-5-20251001)")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("baseline", help="run suite and save result as baseline")
    sp.add_argument("config")
    sp.add_argument("--provider", help="override task provider")
    sp.add_argument("--model", help="override task model")
    sp.set_defaults(func=cmd_baseline)

    sp = sub.add_parser("gate", help="run suite; exit 1 on regression vs baseline")
    sp.add_argument("config")
    sp.add_argument("--out", help="write full JSON result here")
    sp.add_argument("--provider", help="override task provider")
    sp.add_argument("--model", help="override task model")
    sp.set_defaults(func=cmd_gate)

    sp = sub.add_parser("dashboard", help="render self-contained HTML report")
    sp.add_argument("config")
    sp.add_argument("--out", default="report.html", help="output path (default: report.html)")
    sp.add_argument("--provider", help="override task provider (e.g. anthropic)")
    sp.add_argument("--model", help="override task model (e.g. claude-haiku-4-5-20251001)")
    sp.set_defaults(func=cmd_dashboard)

    sp = sub.add_parser("sweep", help="compare suite across multiple model/prompt variants")
    sp.add_argument("config")
    sp.add_argument(
        "--variants", nargs="+", required=True,
        metavar="PROVIDER:MODEL[:PROMPT_PATH]",
        help="variants to compare, e.g. mock:mock-1:prompts/v1.txt",
    )
    sp.add_argument("--out", help="write full JSON results here")
    sp.set_defaults(func=cmd_sweep)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
