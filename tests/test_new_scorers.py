from llm_eval.config import Case
from llm_eval.scorers import CostBudget, LatencyBudget


def _case():
    return Case(id="t", input={})


def test_latency_budget_pass():
    sc = LatencyBudget(budget_ms=1000.0)
    result = sc.score(_case(), "output", latency_ms=500.0)
    assert result.score == 1.0
    assert "500" in result.detail


def test_latency_budget_fail():
    sc = LatencyBudget(budget_ms=1000.0)
    result = sc.score(_case(), "output", latency_ms=1500.0)
    assert result.score == 0.0
    assert "1500" in result.detail


def test_latency_budget_default_budget():
    sc = LatencyBudget()
    assert sc.score(_case(), "output", latency_ms=4999.0).score == 1.0
    assert sc.score(_case(), "output", latency_ms=5001.0).score == 0.0


def test_cost_budget_pass():
    sc = CostBudget(budget_usd=0.01)
    result = sc.score(_case(), "output", cost_usd=0.001)
    assert result.score == 1.0


def test_cost_budget_fail():
    sc = CostBudget(budget_usd=0.001)
    result = sc.score(_case(), "output", cost_usd=0.01)
    assert result.score == 0.0


def test_existing_scorers_accept_runtime_kwargs():
    from llm_eval.scorers import Contains, ExactMatch, RegexMatch

    c = _case(ref="hello")
    # These should not raise TypeError when extra runtime kwargs are passed
    ExactMatch().score(c, "hello", latency_ms=100.0, cost_usd=0.001)
    Contains().score(c, "hello world", latency_ms=100.0)
    RegexMatch(pattern=r"\w+").score(c, "hello", cost_usd=0.0)


def _case(ref=None):
    return Case(id="t", input={}, reference=ref)
