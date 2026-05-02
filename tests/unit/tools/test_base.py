from __future__ import annotations

import pytest

from accela_mcp.api.errors import AccelaAPIError
from accela_mcp.tools._base import (
    TOOL_LIMIT_MAX,
    TOOL_MAX_RESULTS_CEILING,
    clamp_limit,
    clamp_max_results,
    clamp_offset,
    first_result,
    normalize_yn,
    tool_call,
)


class TestClampLimit:
    def test_default_when_none(self) -> None:
        assert clamp_limit(None) == 25

    def test_pass_through(self) -> None:
        assert clamp_limit(50) == 50

    def test_clamped_to_max(self) -> None:
        assert clamp_limit(1000) == TOOL_LIMIT_MAX

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            clamp_limit(0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            clamp_limit(-1)

    def test_non_int_rejected(self) -> None:
        with pytest.raises(ValueError):
            clamp_limit("25")  # type: ignore[arg-type]


class TestClampMaxResults:
    def test_default_when_none(self) -> None:
        assert clamp_max_results(None) == 1000

    def test_pass_through(self) -> None:
        assert clamp_max_results(2500) == 2500

    def test_clamped_to_ceiling(self) -> None:
        assert clamp_max_results(999_999) == TOOL_MAX_RESULTS_CEILING

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            clamp_max_results(0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            clamp_max_results(-1)

    def test_non_int_rejected(self) -> None:
        with pytest.raises(ValueError):
            clamp_max_results("1000")  # type: ignore[arg-type]


class TestClampOffset:
    def test_default(self) -> None:
        assert clamp_offset(None) == 0

    def test_pass_through(self) -> None:
        assert clamp_offset(100) == 100

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            clamp_offset(-1)


class TestFirstResult:
    def test_first_of_array(self) -> None:
        assert first_result({"result": [{"id": 1}, {"id": 2}]}) == {"id": 1}

    def test_dict_result_returned_as_is(self) -> None:
        assert first_result({"result": {"x": 1}}) == {"x": 1}

    def test_empty_array_returns_none(self) -> None:
        assert first_result({"result": []}) is None

    def test_missing_result(self) -> None:
        assert first_result({}) is None


class TestNormalizeYn:
    def test_y_n(self) -> None:
        assert normalize_yn("Y") is True
        assert normalize_yn("n") is False

    def test_native_bool(self) -> None:
        assert normalize_yn(True) is True
        assert normalize_yn(False) is False

    def test_other_string(self) -> None:
        assert normalize_yn("Maybe") is None

    def test_none(self) -> None:
        assert normalize_yn(None) is None


class TestToolCall:
    @pytest.mark.asyncio
    async def test_returns_value_on_success(self) -> None:
        @tool_call("hello")
        async def f(x: int) -> dict[str, int]:
            return {"x": x}

        assert await f(x=1) == {"x": 1}

    @pytest.mark.asyncio
    async def test_translates_accela_error(self) -> None:
        @tool_call("explode")
        async def f() -> dict[str, int]:
            raise AccelaAPIError(
                status=500,
                code="emse_error",
                message="EMSE script blew up",
                trace_id="t",
            )

        out = await f()
        assert out["error"] == "accela_api_error"
        assert out["trace_id"] == "t"
        assert out["hint"]  # EMSE detected

    @pytest.mark.asyncio
    async def test_translates_value_error(self) -> None:
        @tool_call("validate")
        async def f() -> dict[str, int]:
            raise ValueError("bad input")

        out = await f()
        assert out["error"] == "invalid_input"
        assert out["message"] == "bad input"
