from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.api.batch import batch, batch_get, make_sub_request, split_results
from accela_mcp.api.client import AccelaClient


def test_make_sub_request_minimal() -> None:
    sub = make_sub_request("get", "/v4/records/X")
    assert sub == {"method": "GET", "relativeUrl": "/v4/records/X"}


def test_make_sub_request_with_body_and_agency_override() -> None:
    sub = make_sub_request("POST", "/v4/records", body={"x": 1}, agency_override="OTHER")
    assert sub["method"] == "POST"
    assert sub["body"] == {"x": 1}
    assert sub["headers"] == {"x-accela-agency": "OTHER"}


@pytest.mark.asyncio
@respx.mock
async def test_batch_returns_sub_responses(client: AccelaClient) -> None:
    route = respx.post("https://apis.test.example/v4/batch").mock(
        return_value=Response(
            200,
            json={
                "result": [
                    {"status": 200, "result": [{"id": "A"}]},
                    {"status": 401, "code": "unauthorized", "message": "x"},
                ]
            },
        )
    )
    sub_responses = await batch(
        client,
        [
            make_sub_request("GET", "/v4/records/A"),
            make_sub_request("GET", "/v4/records/B"),
        ],
    )
    assert route.called
    assert len(sub_responses) == 2
    successes, failures = split_results(sub_responses)
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0]["status"] == 401


@pytest.mark.asyncio
async def test_batch_empty_input() -> None:
    # Easier to assert: an empty input never issues a request and returns [].
    out = await batch(_NoopClient(), [])  # type: ignore[arg-type]
    assert out == []


class _NoopClient:
    async def post(self, *args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("batch should not call post() on empty input")


@pytest.mark.asyncio
@respx.mock
async def test_batch_get_helper(client: AccelaClient) -> None:
    route = respx.post("https://apis.test.example/v4/batch").mock(
        return_value=Response(200, json={"result": [{"status": 200, "result": []}]})
    )
    await batch_get(client, ["/v4/records/A"])
    body = route.calls.last.request.read()
    assert b"GET" in body
    assert b"/v4/records/A" in body


@pytest.mark.asyncio
@respx.mock
async def test_batch_chunking(client: AccelaClient) -> None:
    # Two POSTs because chunk_size=2 and we send 3 sub-requests.
    route = respx.post("https://apis.test.example/v4/batch").mock(
        side_effect=[
            Response(
                200,
                json={"result": [{"status": 200, "result": []}, {"status": 200, "result": []}]},
            ),
            Response(200, json={"result": [{"status": 200, "result": []}]}),
        ]
    )
    out = await batch_get(client, ["/v4/a", "/v4/b", "/v4/c"], chunk_size=2)
    assert route.call_count == 2
    assert len(out) == 3
