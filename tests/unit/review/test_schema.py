"""Migrated cross-tool review regressions."""

from __future__ import annotations

import json

import pytest

from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewErrorCategory,
    parse_review_json,
    review_json_schema,
)
from tests.support.review_helpers import (
    VALID_REVIEW_JSON,
)
from tests.support.review_helpers import finding as _finding


def test_parse_review_json_accepts_valid_findings():
    result = parse_review_json(VALID_REVIEW_JSON)
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity == "MUST-FIX"
    assert finding.file == "scripts/lib/example.py"
    assert finding.line == 12


@pytest.mark.parametrize(
    "payload, match",
    [
        ("not-json", "malformed"),
        ('{"findings": {}}', "findings list"),
        ('{"findings": [{}]}', "severity"),
        ('{"findings": [{"severity": "LOW"}]}', "invalid"),
        (
            '{"findings":[{"severity":"MUST-FIX","file":"x.py","line":"1",'
            '"title":"t","rationale":"r","suggested_action":"a","confidence":"high"}]}',
            "line",
        ),
        (
            '{"findings":[{"severity":"MUST-FIX","file":"x.py","line":true,'
            '"title":"t","rationale":"r","suggested_action":"a","confidence":"high"}]}',
            "line",
        ),
        (
            '{"findings":[{"severity":"MUST-FIX","file":"/tmp/x","line":1,'
            '"title":"t","rationale":"r","suggested_action":"a","confidence":"high"}]}',
            "repo-relative",
        ),
        (
            '{"findings":[{"severity":"MUST-FIX","file":"x.py","line":1,'
            '"title":"t","rationale":"r","suggested_action":"a","confidence":"certain"}]}',
            "confidence",
        ),
    ],
)
def test_parse_review_json_rejects_malformed_or_missing_required_fields(payload: str, match: str):
    with pytest.raises(CrossToolReviewError, match=match):
        parse_review_json(payload)


@pytest.mark.parametrize("bad_file", ["/tmp/x", "../secret", "a\nb", "a|b", ""])
def test_parse_review_json_rejects_untrusted_file_display_values(bad_file: str):
    payload = {
        "findings": [
            {
                "severity": "MUST-FIX",
                "file": bad_file,
                "line": 1,
                "title": "Path spoof",
                "rationale": "Bad display path",
                "suggested_action": "Reject it",
                "confidence": "high",
            }
        ]
    }
    with pytest.raises(CrossToolReviewError):
        parse_review_json(json.dumps(payload))


def test_parser_rejects_extra_root_and_finding_keys():
    with pytest.raises(CrossToolReviewError) as root_error:
        parse_review_json('{"findings":[],"verdict":"clean"}')
    with pytest.raises(CrossToolReviewError) as finding_error:
        parse_review_json(
            '{"findings":[{"severity":"NITPICK","file":"x.py","line":1,'
            '"title":"t","rationale":"r","suggested_action":"a",'
            '"confidence":"high","extra":true}]}'
        )

    assert root_error.value.category.value == "INVALID_REVIEWER_JSON"
    assert finding_error.value.category.value == "INVALID_REVIEWER_JSON"


def test_verdict_without_security_lens_is_invalid_reviewer_json():
    """Escaping bug: the issue 89 shape, findings only, persists as CLEAN_ADVISORY exit 0."""
    with pytest.raises(CrossToolReviewError, match="security_lens") as error:
        parse_review_json('{"findings": []}')
    assert error.value.category == ReviewErrorCategory.INVALID_REVIEWER_JSON


@pytest.mark.parametrize(
    "lens, match",
    [
        ({"finding": 0, "checks": ["s"], "evidence": "e"}, "security_lens.finding must index"),
        ({"finding": 2, "checks": ["s"], "evidence": "e"}, "security_lens.finding must index"),
        ({"finding": True, "checks": ["s"], "evidence": "e"}, "security_lens.finding must index"),
        ({"finding": "1", "checks": ["s"], "evidence": "e"}, "security_lens.finding must index"),
        ({"finding": 1.0, "checks": ["s"], "evidence": "e"}, "security_lens.finding must index"),
        ({"checks": ["s"], "evidence": "e"}, "security_lens.finding must be an integer or null"),
        ({"finding": None, "evidence": "e"}, "security_lens.checks"),
        ({"finding": None, "checks": [], "evidence": "e"}, "security_lens.checks"),
        ({"finding": None, "checks": "secrets", "evidence": "e"}, "security_lens.checks"),
        ({"finding": None, "checks": ["s", " "], "evidence": "e"}, "security_lens.checks"),
        ({"finding": None, "checks": ["s"], "evidence": " "}, "security_lens.evidence"),
        ({"finding": None, "checks": ["s"]}, "security_lens.evidence"),
        (
            {"finding": None, "checks": ["s"], "evidence": "e", "verdict": "clean"},
            "security_lens contains unknown keys",
        ),
        ("verified clean", "must contain security_lens"),
    ],
)
def test_parser_refuses_a_security_lens_that_says_nothing(lens: object, match: str):
    """Escaping bug: a schema-valid-looking object with no content passes the trust boundary,
    or a bad lens field is reported under the finding label (plan-check finding 3)."""
    payload = json.dumps({"findings": [_finding("x.py", 1)], "security_lens": lens})
    with pytest.raises(CrossToolReviewError, match=match) as error:
        parse_review_json(payload)
    assert error.value.category == ReviewErrorCategory.INVALID_REVIEWER_JSON
    assert "finding." not in str(error.value)


def test_schema_requires_a_non_empty_security_lens():
    """Escaping bug: plan-check finding 2, a structured-output reviewer emits an empty checks list
    and is blocked by the parser after a costly run."""
    schema = json.loads(review_json_schema())
    lens = schema["properties"]["security_lens"]
    assert lens["additionalProperties"] is False
    assert lens["required"] == ["finding", "checks", "evidence"]
    assert set(lens["properties"]) == {"finding", "checks", "evidence"}
    assert lens["properties"]["finding"] == {"minimum": 1, "type": ["integer", "null"]}
    assert lens["properties"]["checks"] == {
        "items": {"type": "string"},
        "minItems": 1,
        "type": "array",
    }
    assert lens["properties"]["evidence"] == {"type": "string"}
