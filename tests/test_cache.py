import tempfile
from pathlib import Path

from llm_eval.cache import CachedClient
from llm_eval.clients import MockClient


def test_cache_returns_same_text():
    with tempfile.TemporaryDirectory() as tmp:
        inner = MockClient()
        cached = CachedClient(inner, cache_dir=tmp)

        first = cached.complete("hello world", temperature=0.0, max_tokens=50)
        second = cached.complete("hello world", temperature=0.0, max_tokens=50)

        assert first.text == second.text
        assert first.input_tokens == second.input_tokens


def test_cache_writes_one_file_per_unique_call():
    with tempfile.TemporaryDirectory() as tmp:
        inner = MockClient()
        cached = CachedClient(inner, cache_dir=tmp)

        cached.complete("prompt A", temperature=0.0, max_tokens=50)
        cached.complete("prompt A", temperature=0.0, max_tokens=50)  # cache hit
        cached.complete("prompt B", temperature=0.0, max_tokens=50)  # new key

        files = list(Path(tmp).iterdir())
        assert len(files) == 2


def test_cache_temperature_is_part_of_key():
    with tempfile.TemporaryDirectory() as tmp:
        inner = MockClient()
        cached = CachedClient(inner, cache_dir=tmp)

        cached.complete("prompt", temperature=0.0, max_tokens=50)
        cached.complete("prompt", temperature=0.5, max_tokens=50)

        files = list(Path(tmp).iterdir())
        assert len(files) == 2


def test_cache_creates_dir_if_missing():
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "nested" / "cache"
        inner = MockClient()
        cached = CachedClient(inner, cache_dir=cache_path)
        cached.complete("hello", temperature=0.0, max_tokens=10)
        assert cache_path.is_dir()
