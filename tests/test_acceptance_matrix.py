"""Regression tests for the issue-20 acceptance evidence contract."""

import scripts.acceptance_matrix as acceptance_matrix
from scripts.acceptance_matrix import _post_remote, _summarize


def test_partial_optimizer_is_recorded_as_withheld_not_certified():
    result = _summarize(
        "partial",
        {"champion": "Ahri"},
        (
            200,
            {
                "combat": {
                    "participants": [{"participant_id": "main"}],
                    "timeline_coverage": {"complete": True},
                }
            },
        ),
        (
            200,
            {
                "items": ["Rabadon's Deathcap"],
                "boots": "Sorcerer's Shoes",
                "is_certified_best": False,
                "search_timeline_coverage": {
                    "complete": False,
                    "note": "coarse candidate evaluations were withheld",
                },
            },
        ),
    )

    assert result["success"] is True
    assert result["outcome"] == "withheld"
    assert result["withheld"] is True
    assert result["build"] == {
        "items": ["Rabadon's Deathcap"],
        "boots": "Sorcerer's Shoes",
    }
    assert result["origin"] == "local:test_client"
    assert result["request_paths"] == {
        "calculate": "/api/calculate",
        "optimize": "/api/optimize",
    }
    assert result["click_state"] == {
        "calculate_submitted": True,
        "optimize_submitted": True,
    }


def test_invalid_calculation_request_is_not_a_matrix_pass():
    result = _summarize(
        "invalid",
        {},
        (400, {"error": "bad request"}),
        (400, {"error": "bad request"}),
    )

    assert result["success"] is False
    assert result["outcome"] == "invalid_request"


def test_optimizer_http_failure_is_not_misclassified_as_withheld():
    result = _summarize(
        "optimizer-down",
        {"champion": "Ahri"},
        (200, {"combat": {"participants": []}}),
        (500, {"error": "backend down"}),
    )

    assert result["success"] is False
    assert result["outcome"] == "optimizer_error"
    assert result["withheld"] is False
    assert result["withheld_reason"] == "backend down"


def test_non_object_success_body_is_recorded_as_withheld_error():
    result = _summarize(
        "malformed-body",
        {"champion": "Ahri"},
        (200, {"combat": {"participants": []}}),
        (200, ["not", "an", "object"]),
    )

    assert result["success"] is False
    assert result["outcome"] == "optimizer_error"
    assert result["withheld"] is False
    assert result["withheld_reason"] == "optimizer response was not a JSON object"


def test_remote_private_calculator_gate_is_actionable(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"<html><title>Scryglass Private calculator</title></html>"

    monkeypatch.setattr(
        acceptance_matrix, "urlopen", lambda *_args, **_kwargs: Response()
    )

    status, body = acceptance_matrix._post_remote(
        "https://example.test", "/api/optimize", {}
    )

    assert status == 200
    assert body["error"] == (
        "remote deployment requires authentication (private calculator gate)"
    )


def test_malformed_optimizer_coverage_is_recorded_as_error():
    result = _summarize(
        "malformed-coverage",
        {"champion": "Ahri"},
        (200, {"combat": {"participants": []}}),
        (200, {"search_timeline_coverage": ["not", "an", "object"]}),
    )

    assert result["success"] is False
    assert result["outcome"] == "optimizer_error"
    assert result["withheld"] is False


def test_missing_optimizer_certification_fields_are_recorded_as_error():
    result = _summarize(
        "missing-schema",
        {"champion": "Ahri"},
        (200, {"combat": {"participants": []}}),
        (200, {"search_timeline_coverage": {}}),
    )

    assert result["success"] is False
    assert result["outcome"] == "optimizer_error"
    assert result["withheld"] is False


def test_remote_non_json_response_is_recorded_instead_of_crashing(monkeypatch):
    class Response:
        status = 502

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"<html>gateway unavailable</html>"

    monkeypatch.setattr(
        acceptance_matrix, "urlopen", lambda *_args, **_kwargs: Response()
    )

    status, body = _post_remote("https://example.test", "/api/calculate", {})

    assert status == 502
    assert body["error"] == "remote response was not valid JSON"
    assert "gateway unavailable" in body["body_preview"]
