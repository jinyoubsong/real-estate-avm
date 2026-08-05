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


@responses.activate
def test_collect_geocodes_skips_masked_jibun(db_engine, monkeypatch):
    """지번이 '*'로 마스킹된 주소는 좌표를 구할 수 없으니 조회 자체를 건너뛴다."""
    monkeypatch.setenv("VWORLD_API_KEY", "dummy-key")
    _seed_trade(db_engine, "서울특별시 종로구 가회동 *")
    responses.add(responses.GET, ENDPOINT, json=json.loads(read_fixture("vworld_geocode_ok.json")), status=200)

    saved = collect_geocodes(engine=db_engine)

    assert saved == 0
    assert len(responses.calls) == 0
    with get_session(db_engine) as db:
        assert db.query(GeoCache).count() == 0


def test_collect_geocodes_requires_api_key(db_engine, monkeypatch):
    monkeypatch.delenv("VWORLD_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        collect_geocodes(engine=db_engine)


def _seed_trades(engine, addresses: list[str]):
    with get_session(engine) as db:
        for i, address in enumerate(addresses):
            db.add(
                Trade(
                    property_type="apt",
                    region_code="11110",
                    deal_date=date(2024, 1, 15),
                    building_name="테스트아파트",
                    jibun=str(i),
                    area_m2=84.93,
                    floor=10,
                    build_year=2001,
                    price_krw=2_500_000_000 + i,
                    address=address,
                )
            )
        db.commit()


def test_collect_geocodes_commits_progress_incrementally(db_engine, monkeypatch):
    """네트워크 오류로 중간에 실패해도, 그 전까지 처리한 건은 커밋되어 남아 있어야 한다."""
    import avm.collectors.vworld_geocode as vg

    monkeypatch.setenv("VWORLD_API_KEY", "dummy-key")
    addresses = sorted(f"주소{i}" for i in range(5))
    _seed_trades(db_engine, addresses)

    call_count = {"n": 0}

    def fake_geocode(address, api_key, session=None):
        call_count["n"] += 1
        if call_count["n"] == 4:
            raise RuntimeError("네트워크 오류 시뮬레이션")
        return (37.5, 127.0)

    monkeypatch.setattr(vg, "geocode_address", fake_geocode)

    with pytest.raises(RuntimeError):
        vg.collect_geocodes(engine=db_engine, commit_every=2)

    with get_session(db_engine) as db:
        # commit_every=2: 처음 2건 처리 후 커밋됐으므로 실패해도 최소 2건은 남아야 한다
        assert db.query(GeoCache).count() >= 2
