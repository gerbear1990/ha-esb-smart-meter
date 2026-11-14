"""Tests for the ESB Networks portal CSV downloader."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from custom_components.esb_smart_meter.downloader import (
    ESBDownloadError,
    ESBDownloadResult,
    download_latest_csv,
)

CSV_BODY = (
    "MPRN,Meter Serial Number,Read Value,Read Type,Read Date and End Time\n"
    "10001234567,123456,0.500,Active Import Interval (kW),01-01-2026 00:30\n"
    "10001234567,123456,0.250,Active Import Interval (kW),01-01-2026 01:00\n"
)

AUTO_FORM_HTML = (
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN">'
    "<html><body>"
    '<form id="auto" action="https://myaccount.esbnetworks.ie/signin-oidc">'
    '<input name="state" value="s1" />'
    '<input name="client_info" value="c1" />'
    '<input name="code" value="code1" />'
    "</form></body></html>"
)


def _resp(
    text: str = "",
    *,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    raw = content if content is not None else text.encode("utf-8")
    return SimpleNamespace(
        text=text,
        content=raw,
        headers=headers or {},
        raise_for_status=lambda: None,
    )


def _mock_session(get_responses: list[SimpleNamespace], post_responses: list[SimpleNamespace]) -> MagicMock:
    session = MagicMock()
    session.headers = {}
    session.cookies.get_dict.return_value = {
        "x-ms-cpim-csrf": "csrf",
        "x-ms-cpim-trans": "trans",
        "ARRAffinity": "arr",
        "ARRAffinitySameSite": "arrs",
        ".AspNetCore.Cookies": "asp",
    }
    session.get.side_effect = get_responses
    session.post.side_effect = post_responses
    return session


def test_download_latest_csv_happy_path():
    session = _mock_session(
        get_responses=[
            _resp('var SETTINGS = {"transId":"tx1","csrf":"cs1"};'),
            _resp(AUTO_FORM_HTML),
            _resp("ok"),
            _resp("ok"),
            _resp('{"token":"af-token"}'),
        ],
        post_responses=[
            _resp("ok"),
            _resp("ok"),
            _resp(
                content=CSV_BODY.encode("utf-8-sig"),
                headers={"Content-Disposition": 'attachment; filename="hdf_export.csv"'},
            ),
        ],
    )
    with (
        patch("custom_components.esb_smart_meter.downloader.requests.Session", return_value=session),
        patch("custom_components.esb_smart_meter.downloader.sleep"),
    ):
        result = download_latest_csv("user@example.com", "pw", "10001234567")

    assert result == ESBDownloadResult(
        csv_text=CSV_BODY,
        filename="hdf_export.csv",
        rows=2,
    )
    session.close.assert_called_once()


@pytest.mark.parametrize(
    ("get_resps", "post_resps", "match"),
    [
        ([_resp("no settings here")], [], "expected settings"),
        ([_resp("var SETTINGS = {not-json};")], [], "invalid settings"),
        ([_resp('var SETTINGS = {"csrf":"only"};')], [], "invalid settings"),
        (
            [
                _resp('var SETTINGS = {"transId":"tx1","csrf":"cs1"};'),
                _resp("<html>captcha block</html>"),
            ],
            [_resp("ok")],
            "Human verification",
        ),
        (
            [
                _resp('var SETTINGS = {"transId":"tx1","csrf":"cs1"};'),
                _resp('<!DOCTYPE html PUBLIC "-//W3C"><html><body><form id="auto" action="/go"><input name="state" value="s"/></form></body></html>'),
            ],
            [_resp("ok")],
            "missing required field 'client_info'",
        ),
        (
            [
                _resp('var SETTINGS = {"transId":"tx1","csrf":"cs1"};'),
                _resp(AUTO_FORM_HTML),
                _resp("ok"),
                _resp("ok"),
                _resp("not-json"),
            ],
            [_resp("ok"), _resp("ok")],
            "anti-forgery token",
        ),
        (
            [
                _resp('var SETTINGS = {"transId":"tx1","csrf":"cs1"};'),
                _resp(AUTO_FORM_HTML),
                _resp("ok"),
                _resp("ok"),
                _resp('{"token":"af-token"}'),
            ],
            [_resp("ok"), _resp("ok"), _resp(content=b"<html>error</html>")],
            "interval CSV",
        ),
    ],
)
def test_download_latest_csv_error_paths(get_resps, post_resps, match):
    session = _mock_session(get_responses=get_resps, post_responses=post_resps)
    with (
        patch("custom_components.esb_smart_meter.downloader.requests.Session", return_value=session),
        patch("custom_components.esb_smart_meter.downloader.sleep"),
        pytest.raises(ESBDownloadError, match=match),
    ):
        download_latest_csv("user@example.com", "pw", "10001234567")
    session.close.assert_called_once()


def test_download_latest_csv_wraps_request_exception():
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = requests.Timeout("timed out")
    with (
        patch("custom_components.esb_smart_meter.downloader.requests.Session", return_value=session),
        pytest.raises(ESBDownloadError, match="ESB request failed"),
    ):
        download_latest_csv("user@example.com", "pw", "10001234567")
    session.close.assert_called_once()
