from llm_eval.config import Case
from llm_eval.scorers import Contains, ExactMatch, JSONSchemaValid, RegexMatch


def _case(ref=None, ctx=None):
    return Case(id="t", input={}, reference=ref, context=ctx)


def test_exact_match():
    assert ExactMatch().score(_case("hello"), "hello").score == 1.0
    assert ExactMatch().score(_case("hello"), "world").score == 0.0


def test_contains_uses_reference():
    assert Contains().score(_case("Series B"), "raised a Series B round").score == 1.0


def test_contains_any_param():
    sc = Contains(**{"any": ["$40M", "40 million"]})
    assert sc.score(_case(), "the $40M round").score == 1.0
    assert sc.score(_case(), "no figure here").score == 0.0


def test_regex():
    assert RegexMatch(pattern=r"\d+%").score(_case(), "up 8% YoY").score == 1.0


def test_json_schema_valid():
    schema = {"type": "object", "required": ["x"]}
    assert JSONSchemaValid(schema=schema).score(_case(), '{"x": 1}').score == 1.0
    assert JSONSchemaValid(schema=schema).score(_case(), '{"y": 1}').score == 0.0
    assert JSONSchemaValid().score(_case(), "not json").score == 0.0
