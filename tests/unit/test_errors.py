from __future__ import annotations

import httpx
import pytest

from accela_mcp.api.errors import (
    AccelaAPIError,
    RetryableError,
    is_likely_emse_error,
)


class TestAccelaAPIError:
    def test_format_includes_status_code_and_traceid(self) -> None:
        err = AccelaAPIError(
            status=403,
            code="forbidden",
            message="nope",
            trace_id="abc-123",
            method="GET",
            path="/v4/records",
        )
        s = str(err)
        assert "[403 forbidden]" in s
        assert "nope" in s
        assert "abc-123" in s
        assert "GET /v4/records" in s

    def test_to_dict_shape(self) -> None:
        err = AccelaAPIError(
            status=400, code="bad_request", message="x", trace_id="t", path="/v4/r"
        )
        d = err.to_dict()
        assert d["error"] == "accela_api_error"
        assert d["status"] == 400
        assert d["trace_id"] == "t"
        assert d["path"] == "/v4/r"

    def test_from_response_full_envelope(self) -> None:
        request = httpx.Request("GET", "https://apis.test/v4/records")
        response = httpx.Response(
            403,
            request=request,
            json={
                "status": 403,
                "code": "forbidden",
                "message": "no.",
                "more": "extra",
                "traceId": "abc",
            },
        )
        err = AccelaAPIError.from_response(response)
        assert err.status == 403
        assert err.code == "forbidden"
        assert err.trace_id == "abc"
        assert err.more == "extra"
        assert err.method == "GET"
        assert err.path == "/v4/records"

    def test_from_response_non_json_body(self) -> None:
        request = httpx.Request("GET", "https://apis.test/v4/x")
        response = httpx.Response(
            500,
            request=request,
            text="<html>oops</html>",
        )
        err = AccelaAPIError.from_response(response)
        assert err.status == 500
        assert err.code == "unknown"
        assert "html" in err.message

    def test_from_response_explicit_path_overrides(self) -> None:
        request = httpx.Request("GET", "https://apis.test/v4/x")
        response = httpx.Response(404, request=request, json={"code": "not_found", "message": "no"})
        err = AccelaAPIError.from_response(response, path="/v4/explicit", method="POST")
        assert err.path == "/v4/explicit"
        assert err.method == "POST"


class TestEmseHeuristic:
    @pytest.mark.parametrize(
        "msg",
        [
            "EMSE script error",
            "Before-event validation failed",
            "Custom rule blocked the operation",
        ],
    )
    def test_500_with_emse_keyword_detected(self, msg: str) -> None:
        err = AccelaAPIError(status=500, code="x", message=msg)
        assert is_likely_emse_error(err)

    def test_500_without_keyword_not_detected(self) -> None:
        err = AccelaAPIError(status=500, code="x", message="generic server error")
        assert not is_likely_emse_error(err)

    def test_non_500_never_detected(self) -> None:
        err = AccelaAPIError(status=400, code="x", message="emse error")
        assert not is_likely_emse_error(err)


def test_retryable_error_carries_status() -> None:
    e = RetryableError("rate limited", status=429, retry_after=2.5)
    assert e.status == 429
    assert e.retry_after == 2.5
