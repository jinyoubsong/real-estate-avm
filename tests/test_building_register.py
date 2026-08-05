import json

import pytest
import responses

from avm.collectors.base import MissingApiKeyError
from avm.collectors.building_register import (
    EXPOS_ENDPOINT,
    TITLE_ENDPOINT,
    Pnu,
    _approval_year,
    _floor_number,
    lookup_building_spec,
    parse_expos_xml,
    parse_pnu,
    parse_title_xml,
)
from avm.collectors.vworld_geocode import ENDPOINT as VWORLD_ENDPOINT
from conftest import read_fixture

# tests/fixtures/vworld_geocode_ok.json 의 level4LC: "1111017500101230004"
SAMPLE_PNU = "1111017500101230004"


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


def test_parse_title_xml():
    info = parse_title_xml(read_fixture("building_title_sample.xml"))
    assert info == {
        "total_floor_area": 15234.56,
        "plat_area": 3200.5,
        "approval_date": "20090630",
        "main_purpose": "공동주택",
        "ground_floors": 25,
    }


def test_parse_expos_xml():
    units = parse_expos_xml(read_fixture("building_expos_sample.xml"))
    assert len(units) == 2
    assert units[0] == {
        "dong_name": "104동",
        "ho_name": "1301호",
        "exclusive_area": 84.9478,
        "floor_name": "제13층",
    }


@pytest.mark.parametrize(
    "floor_name,expected",
    [("제13층", 13), ("제3층", 3), ("지하1층", -1), ("", 0), ("옥탑1층", 1)],
)
def test_floor_number(floor_name, expected):
    assert _floor_number(floor_name) == expected


@pytest.mark.parametrize(
    "approval_date,expected",
    [("20090630", 2009), ("", 0), ("abcd", 0)],
)
def test_approval_year(approval_date, expected):
    assert _approval_year(approval_date) == expected


def _mock_vworld_ok():
    responses.add(
        responses.GET,
        VWORLD_ENDPOINT,
        json=json.loads(read_fixture("vworld_geocode_ok.json")),
        status=200,
    )


@responses.activate
def test_lookup_building_spec_with_dong_ho(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    _mock_vworld_ok()
    responses.add(responses.GET, TITLE_ENDPOINT, body=read_fixture("building_title_sample.xml"), status=200)
    responses.add(responses.GET, EXPOS_ENDPOINT, body=read_fixture("building_expos_sample.xml"), status=200)

    result = lookup_building_spec("서울특별시 종로구 종로동 123-4", dong_name="104동", ho_name="1301호")

    assert result["warning"] is None
    assert result["area_m2"] == 84.9478
    assert result["floor"] == 13
    assert result["build_year"] == 2009
    assert result["lat"] == pytest.approx(37.5665)


@responses.activate
def test_lookup_building_spec_without_dong_ho_uses_title_totals(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    _mock_vworld_ok()
    responses.add(responses.GET, TITLE_ENDPOINT, body=read_fixture("building_title_sample.xml"), status=200)

    result = lookup_building_spec("서울특별시 종로구 종로동 123-4")

    assert result["area_m2"] == 15234.56
    assert result["floor"] == 25
    assert result["build_year"] == 2009


@responses.activate
def test_lookup_building_spec_unmatched_unit_sets_warning(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    _mock_vworld_ok()
    responses.add(responses.GET, TITLE_ENDPOINT, body=read_fixture("building_title_sample.xml"), status=200)
    responses.add(responses.GET, EXPOS_ENDPOINT, body=read_fixture("building_expos_sample.xml"), status=200)

    result = lookup_building_spec("서울특별시 종로구 종로동 123-4", dong_name="999동", ho_name="9999호")

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
