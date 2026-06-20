"""Model clients behind one interface.

`mock` runs fully offline (deterministic) so CI and `make eval` work with no keys.
`anthropic` / `openai` are thin wrappers — set the API key env var and flip the
provider in the suite config. Every call returns a Completion with token usage and
wall-clock latency so the runner can track cost and p50/p95 without extra plumbing.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class ModelClient:
    def complete(self, prompt: str, *, temperature: float, max_tokens: int) -> Completion:
        raise NotImplementedError


class MockClient(ModelClient):
    """Deterministic stand-in. Echoes a hashed, trimmed view of the prompt so
    scorers have something stable to grade. Lets the whole pipeline run in CI."""

    def __init__(self, model: str = "mock-1"):
        self.model = model

    def complete(self, prompt: str, *, temperature: float, max_tokens: int) -> Completion:
        start = time.perf_counter()
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:6]
        # crude deterministic "summary": first sentence + a tag
        first = prompt.strip().split(".")[0][:200]
        text = f"{first}. [mock:{digest}]"
        latency = (time.perf_counter() - start) * 1000
        return Completion(
            text=text,
            input_tokens=len(prompt.split()),
            output_tokens=len(text.split()),
            latency_ms=latency,
        )


class AnthropicClient(ModelClient):
    def __init__(self, model: str):
        from anthropic import Anthropic  # lazy import; optional dependency

        self.model = model
        self._client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def complete(self, prompt: str, *, temperature: float, max_tokens: int) -> Completion:
        start = time.perf_counter()
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        latency = (time.perf_counter() - start) * 1000
        text = "".join(b.text for b in resp.content if b.type == "text")
        return Completion(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            latency_ms=latency,
        )


class OpenAIClient(ModelClient):
    def __init__(self, model: str):
        from openai import OpenAI  # lazy import; optional dependency

        self.model = model
        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def complete(self, prompt: str, *, temperature: float, max_tokens: int) -> Completion:
        start = time.perf_counter()
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        latency = (time.perf_counter() - start) * 1000
        u = resp.usage
        return Completion(
            text=resp.choices[0].message.content or "",
            input_tokens=u.prompt_tokens,
            output_tokens=u.completion_tokens,
            latency_ms=latency,
        )


def make_client(provider: str, model: str) -> ModelClient:
    provider = provider.lower()
    if provider == "mock":
        return MockClient(model)
    if provider == "anthropic":
        return AnthropicClient(model)
    if provider == "openai":
        return OpenAIClient(model)
    raise ValueError(f"unknown provider: {provider}")


# Rough $/1M tokens for cost estimation. Override per model as needed; keep this
# table honest and current — pricing changes, so treat these as estimates only.
# Prices last verified: 2026-06-18
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # model: (input_usd_per_mtok, output_usd_per_mtok)
    "mock-1": (0.0, 0.0),
    # Anthropic — https://www.anthropic.com/pricing (verified 2026-06-18)
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-5": (15.00, 75.00),
    # Legacy names still in common use
    "claude-3-5-haiku-latest": (0.80, 4.00),
    "claude-3-5-sonnet-latest": (3.00, 15.00),
    "claude-3-opus-latest": (15.00, 75.00),
    # OpenAI — https://openai.com/pricing (verified 2026-06-18)
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICE_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * inp + (output_tokens / 1_000_000) * out
