"""Typed config for an eval suite.

A suite binds three things together:
  - a dataset of cases (golden set, version-controlled)
  - a task (prompt template + model) that produces an output per case
  - a list of scorers that grade each output

Everything is declarative so a run is reproducible from config + dataset alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Case:
    """One evaluation example."""

    id: str
    input: dict[str, Any]          # template variables, e.g. {"document": "..."}
    reference: str | None = None   # gold answer, if the task has one
    context: str | None = None     # source text for groundedness checks
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Case":
        return cls(
            id=str(d["id"]),
            input=d.get("input", {}),
            reference=d.get("reference"),
            context=d.get("context"),
            metadata=d.get("metadata", {}),
        )


@dataclass
class TaskConfig:
    name: str
    prompt_path: str                # path to prompt template (uses {var} fields)
    provider: str = "mock"          # mock | anthropic | openai
    model: str = "mock-1"
    temperature: float = 0.0
    max_tokens: int = 1024


@dataclass
class ScorerConfig:
    type: str                       # registered scorer key
    name: str | None = None         # display name; defaults to type
    params: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0             # weight in the suite's aggregate score
    threshold: float = 0.5          # a case "passes" this scorer at/above this


@dataclass
class SuiteConfig:
    name: str
    dataset: str
    task: TaskConfig
    scorers: list[ScorerConfig]
    # max allowed drop in aggregate score vs baseline before CI fails
    regression_tolerance: float = 0.02

    @classmethod
    def load(cls, path: str | Path) -> "SuiteConfig":
        raw = json.loads(Path(path).read_text())
        return cls(
            name=raw["name"],
            dataset=raw["dataset"],
            task=TaskConfig(**raw["task"]),
            scorers=[ScorerConfig(**s) for s in raw["scorers"]],
            regression_tolerance=raw.get("regression_tolerance", 0.02),
        )


def load_dataset(path: str | Path) -> list[Case]:
    """Load a .jsonl dataset, one Case per line."""
    cases: list[Case] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            cases.append(Case.from_dict(json.loads(line)))
    return cases
