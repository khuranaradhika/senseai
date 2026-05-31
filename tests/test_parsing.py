import pytest
from pydantic import BaseModel

from src.core.parsing import StructuredParseError, extract_json, parse_structured


class Sample(BaseModel):
    vote: str
    confidence: float


def test_plain_json():
    out = parse_structured('{"vote": "BUY", "confidence": 0.8}', Sample)
    assert out.vote == "BUY" and out.confidence == 0.8


def test_markdown_fenced_json():
    raw = '```json\n{"vote": "SELL", "confidence": 0.4}\n```'
    out = parse_structured(raw, Sample)
    assert out.vote == "SELL"


def test_prose_wrapped_json_is_extracted():
    raw = 'Sure! Here is my answer:\n{"vote": "HOLD", "confidence": 0.5}\nHope that helps.'
    out = parse_structured(raw, Sample)
    assert out.vote == "HOLD"


def test_extract_json_isolates_object():
    assert extract_json("noise {\"a\": 1} trailing") == '{"a": 1}'


def test_reprompt_repairs_bad_output():
    calls = {"n": 0}

    def reprompt(_err: str) -> str:
        calls["n"] += 1
        return '{"vote": "BUY", "confidence": 0.9}'

    out = parse_structured("not json at all", Sample, reprompt=reprompt)
    assert out.vote == "BUY"
    assert calls["n"] == 1  # exactly one repair attempt


def test_hard_fail_without_reprompt_raises():
    with pytest.raises(StructuredParseError):
        parse_structured("totally broken", Sample)


def test_second_failure_propagates():
    def reprompt(_err: str) -> str:
        return "still broken"  # second attempt also invalid

    with pytest.raises(StructuredParseError):
        parse_structured("broken", Sample, reprompt=reprompt)


def test_schema_violation_is_caught():
    # missing required field
    with pytest.raises(StructuredParseError):
        parse_structured('{"vote": "BUY"}', Sample)
