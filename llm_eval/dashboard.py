"""Render a run result (or baseline-vs-current diff) to a self-contained HTML report.

No external dependencies — all CSS is inlined, charts are SVG. The output is a
single .html file that can be opened in any browser or published to GitHub Pages.

Usage:
    from llm_eval.dashboard import to_html
    html = to_html(result, baseline=optional_baseline_dict)
    Path("report.html").write_text(html)
"""
from __future__ import annotations

import html as _html
from typing import Any

_CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; background: #f8fafc; color: #1e293b; padding: 24px; }
.wrap { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.5rem; font-weight: 700; }
.meta { color: #64748b; font-size: 0.875rem; margin: 6px 0 24px; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px; }
@media (max-width: 700px) { .cards { grid-template-columns: 1fr 1fr; } }
.card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }
.card-val { font-size: 1.75rem; font-weight: 700; line-height: 1.1; }
.card-lbl { color: #64748b; font-size: 0.75rem; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
.panel { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
.panel h2 { font-size: 1rem; font-weight: 600; color: #334155; margin-bottom: 14px; }
.panel h3 { font-size: 0.88rem; font-weight: 600; color: #475569; margin: 18px 0 8px; border-top: 1px solid #f1f5f9; padding-top: 12px; }
.panel h3:first-child { border-top: none; padding-top: 0; }
.banner { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; margin-bottom: 20px; font-size: 0.9rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
th { text-align: left; padding: 6px 10px; border-bottom: 2px solid #e2e8f0; color: #64748b; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap; }
td { padding: 7px 10px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
code { background: #f1f5f9; padding: 1px 5px; border-radius: 3px; font-size: 0.82rem; font-family: ui-monospace, monospace; }
.pass { color: #16a34a; font-weight: 600; }
.fail { color: #dc2626; font-weight: 600; }
.dpos { color: #16a34a; font-size: 0.78rem; margin-left: 4px; }
.dneg { color: #dc2626; font-size: 0.78rem; margin-left: 4px; }
.dzero { color: #64748b; font-size: 0.78rem; margin-left: 4px; }
.tip { cursor: help; border-bottom: 1px dotted #94a3b8; }
"""

_GREEN = "#16a34a"
_YELLOW = "#ca8a04"
_RED = "#dc2626"
_TRACK = "#e5e7eb"


def _score_color(score: float) -> str:
    if score >= 0.8:
        return _GREEN
    if score >= 0.5:
        return _YELLOW
    return _RED


def _bar(score: float, width: int = 240) -> str:
    """Return an inline SVG horizontal progress bar for score ∈ [0, 1]."""
    fill = max(0, min(width, round(score * width)))
    color = _score_color(score)
    label_x = width + 4
    return (
        f'<svg width="{width + 48}" height="18" style="vertical-align:middle">'
        f'<rect width="{width}" height="14" fill="{_TRACK}" rx="3" y="2"/>'
        f'<rect width="{fill}" height="14" fill="{color}" rx="3" y="2"/>'
        f'<text x="{label_x}" y="13" font-size="11" fill="#374151">{score:.3f}</text>'
        "</svg>"
    )


def _e(s: Any) -> str:
    return _html.escape(str(s))


def _delta_span(d: float) -> str:
    sign = "+" if d >= 0 else ""
    cls = "dpos" if d > 0.001 else ("dneg" if d < -0.001 else "dzero")
    return f'<span class="{cls}">({sign}{d:.3f})</span>'


def to_html(result: dict[str, Any], baseline: dict[str, Any] | None = None) -> str:
    """Render *result* to self-contained HTML, optionally showing a diff vs *baseline*."""
    suite = result["suite"]
    task = result["task"]
    agg = result["aggregate_score"]
    pr = result["pass_rate"]
    lat = result["latency_ms"]
    cost = result["est_cost_usd"]
    n = result["n_cases"]
    scorer_means = result["scorer_means"]

    # ── stat cards ───────────────────────────────────────────────────────────
    agg_color = _score_color(agg)
    cards_html = (
        f'<div class="card"><div class="card-val" style="color:{agg_color}">{agg:.3f}</div>'
        f'<div class="card-lbl">Aggregate Score</div></div>'
        f'<div class="card"><div class="card-val">{pr:.1%}</div>'
        f'<div class="card-lbl">Pass Rate</div></div>'
        f'<div class="card"><div class="card-val">{lat["p50"]:.0f}&thinsp;/&thinsp;{lat["p95"]:.0f}&thinsp;ms</div>'
        f'<div class="card-lbl">Latency p50&thinsp;/&thinsp;p95</div></div>'
        f'<div class="card"><div class="card-val">${cost:.4f}</div>'
        f'<div class="card-lbl">Est. Cost</div></div>'
    )

    # ── baseline banner ───────────────────────────────────────────────────────
    banner_html = ""
    if baseline:
        d = agg - baseline.get("aggregate_score", 0.0)
        banner_html = (
            f'<div class="banner"><b>vs Baseline</b> — aggregate '
            f'{baseline.get("aggregate_score", 0):.3f} → {agg:.3f} {_delta_span(d)}</div>'
        )

    # ── scorer summary ────────────────────────────────────────────────────────
    sc_rows = ""
    for name, mean in scorer_means.items():
        delta_html = ""
        if baseline:
            base_mean = baseline.get("scorer_means", {}).get(name)
            if base_mean is not None:
                delta_html = " " + _delta_span(mean - base_mean)
        sc_rows += f"<tr><td>{_e(name)}</td><td>{_bar(mean)}{delta_html}</td></tr>\n"

    scorer_panel = (
        '<div class="panel"><h2>Scorer Summary</h2>'
        '<table><tr><th>Scorer</th><th>Mean Score</th></tr>\n'
        f"{sc_rows}</table></div>"
    )

    # ── slice breakdown ───────────────────────────────────────────────────────
    slice_html = ""
    slices = result.get("slices", {})
    if slices:
        inner = ""
        for sk, groups in slices.items():
            inner += f"<h3>By {_e(sk)}</h3>"
            inner += "<table><tr><th>Value</th><th>N</th><th>Aggregate</th>"
            for sname in scorer_means:
                inner += f"<th>{_e(sname)}</th>"
            inner += "</tr>\n"
            for val, data in sorted(groups.items()):
                inner += f'<tr><td><b>{_e(val)}</b></td><td>{data["n"]}</td>'
                inner += f'<td>{_bar(data["aggregate"], 120)}</td>'
                for sname in scorer_means:
                    sm = data["scorer_means"].get(sname, 0.0)
                    inner += f"<td>{_bar(sm, 80)}</td>"
                inner += "</tr>\n"
            inner += "</table>"
        slice_html = f'<div class="panel"><h2>Slice Breakdown</h2>{inner}</div>'

    # ── per-case table ────────────────────────────────────────────────────────
    sc_headers = "".join(f"<th>{_e(sname)}</th>" for sname in scorer_means)
    case_rows = ""
    for c in result["cases"]:
        out = c["output"]
        preview = (_e(out[:130]) + "…") if len(out) > 130 else _e(out)
        sc_cells = ""
        for sname, sr in c["scores"].items():
            icon = "&#10003;" if sr["passed"] else "&#10007;"
            cls = "pass" if sr["passed"] else "fail"
            tip = _e(sr.get("detail", "") or "")
            sc_cells += (
                f'<td class="{cls}" style="text-align:center">'
                f'<span class="tip" title="{tip}">{icon} {sr["score"]:.2f}</span></td>'
            )
        lat_ms = c.get("latency_ms")
        lat_cell = f"{lat_ms:.1f}&thinsp;ms" if lat_ms is not None else "—"
        case_rows += (
            f'<tr><td><code>{_e(c["id"])}</code></td>'
            f'<td style="max-width:320px;word-break:break-word"><small>{preview}</small></td>'
            f"{sc_cells}"
            f"<td style='white-space:nowrap'><small>{lat_cell}</small></td></tr>\n"
        )

    case_panel = (
        '<div class="panel"><h2>Per-Case Results</h2>'
        f'<table><tr><th>ID</th><th>Output</th>{sc_headers}<th>Latency</th></tr>\n'
        f"{case_rows}</table></div>"
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LLM Eval — {_e(suite)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>LLM Eval — {_e(suite)}</h1>
  <div class="meta">
    model: <code>{_e(task["provider"])}:{_e(task["model"])}</code>
    &nbsp;&middot;&nbsp; prompt: <code>{_e(task["prompt"])}</code>
    &nbsp;&middot;&nbsp; {n} cases
  </div>
  {banner_html}
  <div class="cards">{cards_html}</div>
  {scorer_panel}
  {slice_html}
  {case_panel}
</div>
</body>
</html>"""
