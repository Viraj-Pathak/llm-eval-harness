"""Disk cache for model completions.

Keys are SHA-256 of (model, temperature, max_tokens, prompt). Cached responses are
stored under .cache/completions/ so re-runs and judge calls don't re-bill real
providers. The MockClient doesn't need this, but wrapping it is harmless.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .clients import Completion, ModelClient


class CachedClient(ModelClient):
    """Wraps any ModelClient and persists completions to disk."""

    def __init__(self, inner: ModelClient, cache_dir: str | Path = ".cache/completions"):
        self._inner = inner
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def complete(self, prompt: str, *, temperature: float, max_tokens: int) -> Completion:
        key_data = json.dumps(
            {
                "model": getattr(self._inner, "model", ""),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "prompt": prompt,
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(key_data.encode()).hexdigest()
        path = self._dir / f"{digest}.json"
        if path.exists():
            d = json.loads(path.read_text())
            return Completion(**d)
        comp = self._inner.complete(prompt, temperature=temperature, max_tokens=max_tokens)
        path.write_text(
            json.dumps(
                {
                    "text": comp.text,
                    "input_tokens": comp.input_tokens,
                    "output_tokens": comp.output_tokens,
                    "latency_ms": comp.latency_ms,
                }
            )
        )
        return comp
