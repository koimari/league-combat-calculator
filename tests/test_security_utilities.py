"""Security contracts for local-only parsing and download helpers."""

from unittest.mock import Mock

import pytest

from src.calculator import data_updater
from src.calculator.passive_parser import _eval_simple_expr


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("60 * 3", 180.0),
        ("(5 + 7) / 4", 3.0),
        ("-2 + +5", 3.0),
    ],
)
def test_simple_expression_parser_supports_only_documented_arithmetic(
    expression, expected
):
    assert _eval_simple_expr(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "2 ** 8",
        "__import__('os')",
        "[1][0]",
        "1 // 1",
    ],
)
def test_simple_expression_parser_rejects_other_python_syntax(expression):
    with pytest.raises(ValueError):
        _eval_simple_expr(expression)


def test_wiki_download_has_timeout_and_checks_http_status(monkeypatch):
    response = Mock(text="<html>ok</html>")
    get = Mock(return_value=response)
    monkeypatch.setattr(data_updater, "_http_get", get, raising=False)

    assert data_updater._download_page("https://wiki.example/item") == response.text
    get.assert_called_once_with("https://wiki.example/item", timeout=30)
    response.raise_for_status.assert_called_once_with()


def test_vendored_json_and_soup_downloads_are_also_bounded(monkeypatch, tmp_path):
    json_response = Mock()
    json_response.json.return_value = {"ok": True}
    soup_response = Mock(text="<html>ok</html>")
    get = Mock(side_effect=[json_response, soup_response])
    monkeypatch.setattr(data_updater._lsd_utils.requests, "get", get)

    result = data_updater._lsd_utils.download_json(
        "https://wiki.example/data.json", use_cache=False
    )
    original_soup_download = getattr(
        data_updater, "_orig_download_soup", data_updater._lsd_utils.download_soup
    )
    original_soup_download(
        "https://wiki.example/page", use_cache=False, dir=str(tmp_path)
    )

    assert result == {"ok": True}
    assert get.call_args_list[0].kwargs["timeout"] == 30
    assert get.call_args_list[1].kwargs["timeout"] == 30
    json_response.raise_for_status.assert_called_once_with()
    soup_response.raise_for_status.assert_called_once_with()
