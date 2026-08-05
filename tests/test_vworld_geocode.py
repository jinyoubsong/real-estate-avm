import json
from datetime import date

import pytest
import responses

from avm.collectors.base import MissingApiKeyError
from avm.collectors.vworld_geocode import (
    ENDPOINT,
    collect_geocodes,
    parse_geocode_response,
    parse_geocode_response_detailed,
)
from avm.db import GeoCache, Trade, get_session
from conftest import read_fixture


def test_parse_geocode_response_ok():
    data = json.loads(read_fixture("vworld_geocode_ok.json"))
    coord = parse_geocode_response(data)
    assert coord == (37.5665, 126.978)


def test_parse_geocode_response_not_found():
    data = json.loads(read_fixture("vworld_geocode_not_found.json"))
    assert parse_geocode_response(data) is None


def test_parse_geocode_response_detailed_includes_pnu():
    data = json.loads(read_fixture("vworld_geocode_ok.json"))
    detailed = parse_geocode_response_detailed(data)
    assert detailed == {
        "lat": 37.5665,
        "lng": 126.978,
        "pnu": "1111017500101230004",
    }


def test_parse_geocode_response_detailed_not_found():
    data = json.loads(read_fixture("vworld_geocode_not_found.json"))
    assert parse_geocode_response_detailed(data) is None


def _seed_trade(engine, address: str):
    with get_session(engine) as db:
        db.add(
            Trade(
                property_type="apt",
                region_code="11110",
                deal_date=date(2024, 1, 15),
                building_name="테스트아파트",
                jibun="123-4",
                area_m2=84.93,
                floor=10,
                build_year=2001,
                price_krw=2_500_000_000,
                address=address,
            )
        )
        db.commit()


@responses.activate
def test_collect_geocodes_saves_new_address(db_engine, monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy-key")
    _seed_trade(db_engine, "서울특별시 종로구 종로동 123-4")
    responses.add(responses.GET, ENDPOINT, json=json.loads(read_fixture("vworld_geocode_ok.json")), status=200)

    saved = collect_geocodes(engine=db_engine)

    assert saved == 1
    with get_session(db_engine) as db:
        row = db.get(GeoCache, "서울특별시 종로구 종로동 123-4")
        assert row is not None
        assert row.lat == pytest.approx(37.5665)
        assert row.lng == pytest.approx(126.978)


@responses.activate
def test_collect_geocodes_skips_already_cached(db_engine, monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "dummy-key")
    _seed_trade(db_engine, "서울특별시 종로구 종로동 123-4")
    with get_session(db_engine) as db:
        db.add(GeoCache(address="서울특별시 종로구 종로동 123-4", lat=1.0, lng=2.0))
        db.commit()

    saved = collect_geocodes(engine=db_engine)

    assert saved == 0


def test_collect_geocodes_requires_api_key(db_engine, monkeypatch):
    monkeypatch.delenv("VWORLD_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        collect_geocodes(engine=db_engine)
