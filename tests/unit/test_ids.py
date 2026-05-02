from __future__ import annotations

import pytest

from accela_mcp.utils.ids import is_safe_api_path, join_ids, parse_record_id


class TestParseRecordId:
    def test_parses_full_id(self) -> None:
        parts = parse_record_id("ISLANDTON-14CAP-00000-000I4")
        assert parts.service_provider_code == "ISLANDTON"
        assert parts.unique == "14CAP-00000-000I4"
        assert parts.full == "ISLANDTON-14CAP-00000-000I4"

    def test_strips_whitespace(self) -> None:
        assert (
            parse_record_id("  NULLISLAND-22BLD-12345-001A4  ").service_provider_code
            == "NULLISLAND"
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "not-an-id",
            "ISLANDTON-14CAP",
            "lower-14CAP-00000-000I4",  # agency must start with uppercase
            "AGENCY 14CAP-00000-000I4",  # space
        ],
    )
    def test_rejects_garbage(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_record_id(bad)


class TestIsSafeApiPath:
    @pytest.mark.parametrize(
        "good",
        [
            "/v4/records",
            "/v4/records/ABC-1-2-3",
            "/v4/inspections/123/checklists",
            "/v4/settings/records/types",
            "/v4/records?status=Submitted",
        ],
    )
    def test_accepts_v4_paths(self, good: str) -> None:
        assert is_safe_api_path(good)

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "/v3/records",
            "v4/records",  # missing leading slash
            "/v4/records/../etc/passwd",
            "/v4//records",
            "https://apis.accela.com/v4/records",
            "/V4/records",  # case-sensitive lowercase only
        ],
    )
    def test_rejects_unsafe_paths(self, bad: str) -> None:
        assert not is_safe_api_path(bad)


class TestJoinIds:
    def test_simple_join(self) -> None:
        assert join_ids(["1", "2", "3"]) == "1,2,3"

    def test_dedups_and_strips(self) -> None:
        assert join_ids(["  1 ", "1", "2"]) == "1,2"

    def test_empty_list_raises(self) -> None:
        with pytest.raises(ValueError):
            join_ids([])

    def test_empty_entry_raises(self) -> None:
        with pytest.raises(ValueError):
            join_ids(["1", "", "2"])
