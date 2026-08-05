import json

import pytest
import responses

from avm.collectors.base import MissingApiKeyError
from avm.collectors.building_register import (
    EXPOS_ENDPOINT,
    TITLE_ENDPOINT,
    Pnu,
    _approval_year,
    _normalize_unit_token,
    lookup_building_spec,
    parse_expos_json,
    parse_pnu,
    parse_title_json,
    resolve_pnu,
    suggest_property_type,
)
from avm.collectors.vworld_geocode import ENDPOINT as VWORLD_ENDPOINT
from conftest import read_fixture

# tests/fixtures/vworld_geocode_ok.json 의 level4LC: "1111017500101230004"
SAMPLE_PNU = "1111017500101230004"


def _json_fixture(name: str) -> dict:
    return json.loads(read_fixture(name))


def test_parse_pnu_general_lot():
    pnu = parse_pnu(SAMPLE_PNU)
    assert pnu == Pnu(sigungu_cd="11110", bjdong_cd="17500", plat_gb_cd="0", bun="0123", ji="0004")


def test_parse_pnu_mountain_lot():
    code = "1111017500" + "2" + "0123" + "0004"  # 산여부='2'
    pnu = parse_pnu(code)
    assert pnu.plat_gb_cd == "1"


def test_parse_pnu_too_short_raises():
    with pytest.raises(ValueError):
        parse_pnu("123")


@pytest.mark.parametrize(
    "value,expected",
    [("104동", "104"), ("1301호", "1301"), ("102", "102"), (" 104동 ", "104")],
)
def test_normalize_unit_token(value, expected):
    assert _normalize_unit_token(value) == expected


@pytest.mark.parametrize(
    "approval_date,expected",
    [("20090630", 2009), ("", 0), ("abcd", 0)],
)
def test_approval_year(approval_date, expected):
    assert _approval_year(approval_date) == expected


@pytest.mark.parametrize(
    "main_purpose,etc_purpose,expected",
    [
        ("공동주택", "아파트", "apt"),
        ("업무시설", "오피스텔", "offi"),
        ("공동주택", "다세대주택", "rh"),
        ("단독주택", "다가구주택", "sh"),
        ("공동주택", "", None),
        ("", "", None),
    ],
)
def test_suggest_property_type(main_purpose, etc_purpose, expected):
    assert suggest_property_type(main_purpose, etc_purpose) == expected


@responses.activate
def test_resolve_pnu_success():
    _mock_vworld_ok()
    lookup = resolve_pnu("서울특별시 종로구 종로동 123-4", "dummy")
    assert lookup.pnu == Pnu(sigungu_cd="11110", bjdong_cd="17500", plat_gb_cd="0", bun="0123", ji="0004")
    assert lookup.lat == pytest.approx(37.5665)
    assert lookup.warning is None


@responses.activate
def test_resolve_pnu_not_found():
    responses.add(
        responses.GET,
        VWORLD_ENDPOINT,
        json=json.loads(read_fixture("vworld_geocode_not_found.json")),
        status=200,
    )
    lookup = resolve_pnu("존재하지않는주소 0-0", "dummy")
    assert lookup.pnu is None
    assert "찾지 못했습니다" in lookup.warning


def test_parse_title_json_returns_one_row_per_dong():
    titles = parse_title_json(_json_fixture("building_title_sample.json"))
    assert len(titles) == 2
    assert titles[0]["dong_name"] == "103동"
    assert titles[0]["total_floor_area"] == 1645.0801
    assert titles[0]["approval_date"] == "20090320"
    assert titles[0]["main_purpose"] == "공동주택"
    assert titles[0]["ground_floors"] == 10
    assert titles[1]["dong_name"] == "104동"
    assert titles[1]["ground_floors"] == 13


def test_parse_expos_json_includes_gb_code():
    units = parse_expos_json(_json_fixture("building_expos_sample.json"))
    assert len(units) == 3
    exclusive = [u for u in units if u["expos_gb"] == "1"]
    assert len(exclusive) == 2
    assert exclusive[0] == {
        "dong_name": "104동",
        "ho_name": "102",
        "exclusive_area": 59.9426,
        "floor": 1,
        "floor_name": "1층",
        "expos_gb": "1",
    }


def test_parse_expos_json_handles_empty_items_string():
    units = parse_expos_json(_json_fixture("building_expos_empty.json"))
    assert units == []


def _mock_vworld_ok():
    responses.add(
        responses.GET,
        VWORLD_ENDPOINT,
        json=json.loads(read_fixture("vworld_geocode_ok.json")),
        status=200,
    )


@responses.activate
def test_lookup_building_spec_with_dong_ho_filters_exclusive_only(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    _mock_vworld_ok()
    responses.add(responses.GET, TITLE_ENDPOINT, json=_json_fixture("building_title_sample.json"), status=200)
    responses.add(responses.GET, EXPOS_ENDPOINT, json=_json_fixture("building_expos_sample.json"), status=200)

    result = lookup_building_spec("서울특별시 종로구 종로동 123-4", dong_name="104동", ho_name="102")

    assert result["warning"] is None
    assert result["area_m2"] == 59.9426  # 전유(1)만, 공용(18.3818)은 제외
    assert result["floor"] == 1
    assert result["build_year"] == 2009  # 104동 표제부 사용승인일 기준
    assert result["lat"] == pytest.approx(37.5665)


@responses.activate
def test_lookup_building_spec_accepts_ho_suffix_variants(monkeypatch):
    """사용자가 '1301호'처럼 접미사를 붙여 입력해도 API의 '1301'과 매칭돼야 한다."""
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    _mock_vworld_ok()
    responses.add(responses.GET, TITLE_ENDPOINT, json=_json_fixture("building_title_sample.json"), status=200)
    responses.add(responses.GET, EXPOS_ENDPOINT, json=_json_fixture("building_expos_sample.json"), status=200)

    result = lookup_building_spec("서울특별시 종로구 종로동 123-4", dong_name="104동", ho_name="1301호")

    assert result["area_m2"] == 84.9478
    assert result["floor"] == 13


@responses.activate
def test_lookup_building_spec_without_dong_ho_uses_first_title_row(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    _mock_vworld_ok()
    responses.add(responses.GET, TITLE_ENDPOINT, json=_json_fixture("building_title_sample.json"), status=200)

    result = lookup_building_spec("서울특별시 종로구 종로동 123-4")

    assert result["area_m2"] == 1645.0801
    assert result["floor"] == 10
    assert result["build_year"] == 2009


@responses.activate
def test_lookup_building_spec_unmatched_unit_sets_warning(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    _mock_vworld_ok()
    responses.add(responses.GET, TITLE_ENDPOINT, json=_json_fixture("building_title_sample.json"), status=200)
    responses.add(responses.GET, EXPOS_ENDPOINT, json=_json_fixture("building_expos_sample.json"), status=200)

    result = lookup_building_spec("서울특별시 종로구 종로동 123-4", dong_name="999동", ho_name="9999")

    assert result["area_m2"] is None
    assert "찾지 못해" in result["warning"]


@responses.activate
def test_lookup_building_spec_address_not_found(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    responses.add(
        responses.GET,
        VWORLD_ENDPOINT,
        json=json.loads(read_fixture("vworld_geocode_not_found.json")),
        status=200,
    )

    result = lookup_building_spec("존재하지않는주소 0-0")

    assert result["area_m2"] is None
    assert "찾지 못했습니다" in result["warning"]


def test_lookup_building_spec_requires_vworld_key(monkeypatch):
    monkeypatch.delenv("VWORLD_API_KEY", raising=False)
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    with pytest.raises(MissingApiKeyError):
        lookup_building_spec("서울특별시 종로구 종로동 123-4")


def test_lookup_building_spec_requires_data_go_kr_key(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.delenv("DATA_GO_KR_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        lookup_building_spec("서울특별시 종로구 종로동 123-4")
