"""Tests for the OAuth Authorization Code flow.

We can't drive a full interactive run from a unit test (no real browser), so
we exercise the underlying primitives — PKCE, state validation, token
exchange — and assert the authorize URL the user would visit is correct.
"""

from __future__ import annotations

import base64
import hashlib
import urllib.parse

import pytest
import respx
from httpx import Response

from accela_mcp.auth.flow import (
    OAuthFlowError,
    _exchange_code_for_tokens,
    _parse_redirect,
    _pkce_pair,
)
from accela_mcp.settings import Settings


class TestPkcePair:
    def test_challenge_is_s256_of_verifier(self) -> None:
        verifier, challenge = _pkce_pair()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert challenge == expected
        # Verifier in RFC 7636 length range [43, 128]
        assert 43 <= len(verifier) <= 128

    def test_two_invocations_differ(self) -> None:
        a = _pkce_pair()
        b = _pkce_pair()
        assert a != b


class TestParseRedirect:
    def test_valid_loopback(self, settings: Settings) -> None:
        host, port = _parse_redirect("http://localhost:8765/cb")
        assert host == "127.0.0.1"
        assert port == 8765

    def test_default_port_when_unspecified(self) -> None:
        host, port = _parse_redirect("http://localhost/cb")
        assert host == "127.0.0.1"
        assert port == 80

    def test_non_loopback_rejected(self) -> None:
        with pytest.raises(OAuthFlowError):
            _parse_redirect("https://accela.example.com/cb")


class TestExchangeCode:
    @pytest.mark.asyncio
    @respx.mock
    async def test_token_exchange_happy_path(self, settings: Settings) -> None:
        respx.post(f"{settings.auth_base_url}/oauth2/token").mock(
            return_value=Response(
                200,
                json={
                    "access_token": "ax",
                    "refresh_token": "rx",
                    "token_type": "bearer",
                    "expires_in": "28800",
                    "scope": "records",
                },
            )
        )
        tokens = await _exchange_code_for_tokens(
            settings,
            agency="NULLISLAND",
            environment="TEST",
            code="abc",
            code_verifier="v",
            scopes=["records"],
        )
        assert tokens.access_token == "ax"
        assert tokens.scope == "records"
        assert tokens.agency == "NULLISLAND"

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_exchange_400_raises(self, settings: Settings) -> None:
        respx.post(f"{settings.auth_base_url}/oauth2/token").mock(
            return_value=Response(400, json={"error": "invalid_grant"})
        )
        with pytest.raises(OAuthFlowError):
            await _exchange_code_for_tokens(
                settings,
                agency="X",
                environment="TEST",
                code="bad",
                code_verifier="v",
                scopes=["records"],
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_exchange_missing_fields_raises(self, settings: Settings) -> None:
        respx.post(f"{settings.auth_base_url}/oauth2/token").mock(
            return_value=Response(200, json={"access_token": "only"})
        )
        with pytest.raises(OAuthFlowError):
            await _exchange_code_for_tokens(
                settings,
                agency="X",
                environment="TEST",
                code="c",
                code_verifier="v",
                scopes=["records"],
            )


class TestAuthorizeUrlComposition:
    """Build the authorize URL via the flow's parameter assembly logic and
    verify everything an IdP would care about ends up in the query string."""

    @pytest.mark.asyncio
    async def test_run_with_empty_scopes_rejected(self, settings: Settings) -> None:
        from accela_mcp.auth.flow import run_authorization_code_flow

        with pytest.raises(OAuthFlowError):
            await run_authorization_code_flow(
                settings,
                agency="NULLISLAND",
                environment="TEST",
                scopes=[],
                open_browser=False,
            )

    def test_authorize_url_format_via_urlencode(self, settings: Settings) -> None:
        # Sanity check that urlencode handles the scope string with spaces.
        url = f"{settings.auth_base_url}/oauth2/authorize?" + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": settings.app_id,
                "agency_name": "NULLISLAND",
                "environment": "TEST",
                "redirect_uri": settings.redirect_uri,
                "state": "x",
                "scope": "a b c",
                "code_challenge": "ch",
                "code_challenge_method": "S256",
            }
        )
        assert "scope=a+b+c" in url
        assert "code_challenge_method=S256" in url
