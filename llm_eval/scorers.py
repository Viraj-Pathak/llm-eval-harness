"""Scorers grade a single model output for one case.

Two families:
  - deterministic: exact match, substring, regex, JSON-schema validity. Cheap,
    reproducible, no model call. Use these wherever the spec is checkable.
  - judge-based: an LLM grades against a rubric (quality) or checks whether the
    answer is supported by provided context (groundedness). Use sparingly — they
    cost money and add variance, so pin the judge model and temperature=0.
  - runtime: latency_budget, cost_budget — check per-call performance against a
    threshold. Pass latency_ms / cost_usd via **runtime from the runner.

Every scorer returns a ScoreResult with a score in [0, 1] plus a human-readable
detail so failures are debuggable from the report alone.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .clients import ModelClient
from .config import Case


@dataclass
class ScoreResult:
    score: float          # 0.0 - 1.0
    detail: str = ""


class Scorer:
    type: str = "base"

    def __init__(self, name: str | None = None, **params: Any):
        self.name = name or self.type
        self.params = params

    def score(self, case: Case, output: str, judge: ModelClient | None = None, **runtime: Any) -> ScoreResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Deterministic scorers
# --------------------------------------------------------------------------- #

class ExactMatch(Scorer):
    type = "exact_match"

    def score(self, case, output, judge=None, **_):
        ok = output.strip() == (case.reference or "").strip()
        return ScoreResult(1.0 if ok else 0.0, "" if ok else "output != reference")


class Contains(Scorer):
    type = "contains"

    def score(self, case, output, judge=None, **_):
        needles: list[str] = self.params.get("any", [])
        if not needles and case.reference:
            needles = [case.reference]
        hit = next((n for n in needles if n.lower() in output.lower()), None)
        return ScoreResult(1.0 if hit else 0.0, f"matched {hit!r}" if hit else f"none of {needles}")


class RegexMatch(Scorer):
    type = "regex"

    def score(self, case, output, judge=None, **_):
        pattern = self.params["pattern"]
        ok = re.search(pattern, output) is not None
        return ScoreResult(1.0 if ok else 0.0, f"/{pattern}/ {'matched' if ok else 'no match'}")


class JSONSchemaValid(Scorer):
    """Output must be valid JSON; optionally validate against a JSON Schema."""

    type = "json_schema"

    def score(self, case, output, judge=None, **_):
        try:
            data = json.loads(output)
        except json.JSONDecodeError as e:
            return ScoreResult(0.0, f"invalid JSON: {e}")
        schema = self.params.get("schema")
        if not schema:
            return ScoreResult(1.0, "valid JSON")
        try:
            import jsonschema

            jsonschema.validate(data, schema)
            return ScoreResult(1.0, "schema valid")
        except Exception as e:  # noqa: BLE001 - report any validation failure
            return ScoreResult(0.0, f"schema error: {e}")


class LatencyBudget(Scorer):
    """Passes if this case's latency is under the configured budget_ms threshold."""

    type = "latency_budget"

    def score(self, case, output, judge=None, *, latency_ms: float = 0.0, **_):
        budget = float(self.params.get("budget_ms", 5000.0))
        ok = latency_ms <= budget
        return ScoreResult(
            1.0 if ok else 0.0,
            f"{latency_ms:.1f}ms {'≤' if ok else '>'} {budget:.0f}ms budget",
        )


class CostBudget(Scorer):
    """Passes if this case's estimated cost is under the configured budget_usd threshold."""

    type = "cost_budget"

    def score(self, case, output, judge=None, *, cost_usd: float = 0.0, **_):
        budget = float(self.params.get("budget_usd", 0.01))
        ok = cost_usd <= budget
        return ScoreResult(
            1.0 if ok else 0.0,
            f"${cost_usd:.6f} {'≤' if ok else '>'} ${budget:.6f} budget",
        )


# --------------------------------------------------------------------------- #
# Judge-based scorers
# --------------------------------------------------------------------------- #

_JUDGE_RUBRIC = """You are a strict evaluator. Grade the RESPONSE against the rubric.

RUBRIC:
{rubric}

{ref_block}
RESPONSE:
{output}

Reply with ONLY a JSON object: {{"score": <int 1-5>, "reason": "<one sentence>"}}.
Do not include markdown or any other text."""


class LLMJudge(Scorer):
    """LLM-as-judge against a rubric. Maps a 1-5 grade to [0,1]."""

    type = "llm_judge"

    def score(self, case, output, judge=None, **_):
        if judge is None:
            return ScoreResult(0.0, "no judge client configured")
        ref_block = f"REFERENCE (gold answer):\n{case.reference}\n\n" if case.reference else ""
        prompt = _JUDGE_RUBRIC.format(
            rubric=self.params.get("rubric", "Is the response correct, clear, and complete?"),
            ref_block=ref_block,
            output=output,
        )
        comp = judge.complete(prompt, temperature=0.0, max_tokens=200)
        try:
            parsed = json.loads(_extract_json(comp.text))
            raw = float(parsed["score"])
            return ScoreResult((raw - 1) / 4, parsed.get("reason", ""))
        except Exception as e:  # noqa: BLE001
            return ScoreResult(0.0, f"judge parse error: {e} | raw={comp.text[:120]!r}")


_GROUNDED_RUBRIC = """Determine whether the RESPONSE is fully supported by the CONTEXT.
A response is grounded only if every factual claim it makes appears in the context.

CONTEXT:
{context}

RESPONSE:
{output}

Reply with ONLY JSON: {{"grounded": true|false, "reason": "<one sentence>"}}."""


class Groundedness(Scorer):
    """Checks the output makes no claims absent from the case context (anti-hallucination)."""

    type = "groundedness"

    def score(self, case, output, judge=None, **_):
        if judge is None:
            return ScoreResult(0.0, "no judge client configured")
        if not case.context:
            return ScoreResult(0.0, "case has no context to ground against")
        prompt = _GROUNDED_RUBRIC.format(context=case.context, output=output)
        comp = judge.complete(prompt, temperature=0.0, max_tokens=150)
        try:
            parsed = json.loads(_extract_json(comp.text))
            return ScoreResult(1.0 if parsed["grounded"] else 0.0, parsed.get("reason", ""))
        except Exception as e:  # noqa: BLE001
            return ScoreResult(0.0, f"judge parse error: {e}")


def _extract_json(text: str) -> str:
    """Pull the first {...} block out of a model reply, tolerating stray prose/fences."""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else text


_REGISTRY: dict[str, type[Scorer]] = {
    s.type: s
    for s in (
        ExactMatch, Contains, RegexMatch, JSONSchemaValid,
        LatencyBudget, CostBudget,
        LLMJudge, Groundedness,
    )
}


def build_scorer(type_: str, name: str | None, params: dict[str, Any]) -> Scorer:
    if type_ not in _REGISTRY:
        raise ValueError(f"unknown scorer {type_!r}; have {list(_REGISTRY)}")
    return _REGISTRY[type_](name=name, **params)
