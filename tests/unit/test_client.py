from __future__ import annotations

import pytest
import respx
from httpx import Response

from accela_mcp.api.client import AccelaClient
from accela_mcp.api.errors import AccelaAPIError


@pytest.mark.asyncio
@respx.mock
async def test_get_attaches_required_headers(client: AccelaClient) -> None:
    route = respx.get("https://apis.test.example/v4/records/X").mock(
        return_value=Response(200, json={"result": [{"id": "X"}]})
    )
    await client.get("/v4/records/X")
    request = route.calls.last.request
    assert request.headers["authorization"] == client.tokens.access_token
    assert request.headers["x-accela-appid"] == client.settings.app_id
    assert request.headers["x-accela-environment"] == "TEST"
    assert request.headers["x-accela-agency"] == "NULLISLAND"


@pytest.mark.asyncio
@respx.mock
async def test_drops_none_params(client: AccelaClient) -> None:
    route = respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(200, json={"result": []})
    )
    await client.get("/v4/records", params={"module": "Building", "status": None})
    url = str(route.calls.last.request.url)
    assert "module=Building" in url
    assert "status" not in url


@pytest.mark.asyncio
@respx.mock
async def test_403_raises_immediately(client: AccelaClient) -> None:
    respx.get("https://apis.test.example/v4/records/X").mock(
        return_value=Response(
            403,
            json={
                "status": 403,
                "code": "forbidden",
                "message": "nope",
                "traceId": "abc-123",
            },
        )
    )
    with pytest.raises(AccelaAPIError) as exc:
        await client.get("/v4/records/X")
    assert exc.value.status == 403
    assert exc.value.trace_id == "abc-123"


@pytest.mark.asyncio
@respx.mock
async def test_404_raises_immediately(client: AccelaClient) -> None:
    respx.get("https://apis.test.example/v4/records/MISSING").mock(
        return_value=Response(404, json={"code": "not_found", "message": "missing"})
    )
    with pytest.raises(AccelaAPIError) as exc:
        await client.get("/v4/records/MISSING")
    assert exc.value.status == 404


@pytest.mark.asyncio
@respx.mock
async def test_429_retries_then_succeeds(client: AccelaClient) -> None:
    route = respx.get("https://apis.test.example/v4/records").mock(
        side_effect=[
            Response(429, json={"code": "rate_limited", "message": "slow down"}),
            Response(429, json={"code": "rate_limited", "message": "slow down"}),
            Response(200, json={"result": []}),
        ]
    )
    result = await client.get("/v4/records")
    assert route.call_count == 3
    assert result == {"result": []}


@pytest.mark.asyncio
@respx.mock
async def test_429_retries_exhausted_raises(client: AccelaClient) -> None:
    respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(429, json={"code": "rate_limited", "message": "no"})
    )
    with pytest.raises(AccelaAPIError) as exc:
        await client.get("/v4/records")
    assert exc.value.status == 429


@pytest.mark.asyncio
@respx.mock
async def test_500_retries_once_then_succeeds(client: AccelaClient) -> None:
    route = respx.get("https://apis.test.example/v4/records").mock(
        side_effect=[
            Response(500, json={"code": "server_error", "message": "oops"}),
            Response(200, json={"result": []}),
        ]
    )
    result = await client.get("/v4/records")
    assert route.call_count == 2
    assert result == {"result": []}


@pytest.mark.asyncio
@respx.mock
async def test_502_retried_until_success(client: AccelaClient) -> None:
    route = respx.get("https://apis.test.example/v4/records").mock(
        side_effect=[
            Response(502, text="bad gateway"),
            Response(200, json={"result": []}),
        ]
    )
    result = await client.get("/v4/records")
    assert route.call_count == 2
    assert result == {"result": []}


@pytest.mark.asyncio
@respx.mock
async def test_401_triggers_refresh_then_retries_once(client: AccelaClient) -> None:
    refresh = respx.post("https://auth.test.example/oauth2/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "renewed_token",
                "refresh_token": "renewed_refresh",
                "token_type": "bearer",
                "expires_in": 28800,
                "scope": "records",
            },
        )
    )
    api = respx.get("https://apis.test.example/v4/records/X").mock(
        side_effect=[
            Response(
                401,
                json={"code": "invalid_token", "message": "expired", "traceId": "t-1"},
            ),
            Response(200, json={"result": [{"id": "X"}]}),
        ]
    )
    result = await client.get("/v4/records/X")
    assert refresh.call_count == 1
    assert api.call_count == 2
    assert result["result"][0]["id"] == "X"
    # Verify second request used the refreshed access token.
    second_request = api.calls[1].request
    assert second_request.headers["authorization"] == "renewed_token"


@pytest.mark.asyncio
@respx.mock
async def test_401_after_refresh_then_401_again_surfaces(client: AccelaClient) -> None:
    respx.post("https://auth.test.example/oauth2/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "renewed",
                "refresh_token": "renewed_refresh",
                "token_type": "bearer",
                "expires_in": 28800,
                "scope": "records",
            },
        )
    )
    respx.get("https://apis.test.example/v4/records/X").mock(
        return_value=Response(401, json={"code": "invalid_token", "message": "still expired"})
    )
    with pytest.raises(AccelaAPIError) as exc:
        await client.get("/v4/records/X")
    assert exc.value.status == 401


@pytest.mark.asyncio
@respx.mock
async def test_invalid_json_raises_structured_error(client: AccelaClient) -> None:
    respx.get("https://apis.test.example/v4/records").mock(
        return_value=Response(200, content=b"not json")
    )
    with pytest.raises(AccelaAPIError) as exc:
        await client.get("/v4/records")
    assert exc.value.code == "invalid_json"


@pytest.mark.asyncio
@respx.mock
async def test_post_with_json_body(client: AccelaClient) -> None:
    route = respx.post("https://apis.test.example/v4/search/records").mock(
        return_value=Response(200, json={"result": [], "page": {"hasmore": False}})
    )
    body = {"status": "Submitted"}
    result = await client.post("/v4/search/records", json=body)
    assert result["result"] == []
    sent = route.calls.last.request
    assert sent.headers["content-type"] == "application/json"


@pytest.mark.asyncio
@respx.mock
async def test_request_raw_returns_httpx_response(client: AccelaClient) -> None:
    respx.get("https://apis.test.example/v4/documents/1/download").mock(
        return_value=Response(200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"})
    )
    response = await client.request_raw("GET", "/v4/documents/1/download")
    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n"
    assert response.headers["content-type"] == "image/png"
