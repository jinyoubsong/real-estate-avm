from datetime import date

import pytest
import responses

from avm.collectors.base import MissingApiKeyError
from avm.collectors.molit_trades import ENDPOINT, collect_trades, parse_trades_xml
from avm.db import Trade, get_session
from conftest import read_fixture


def test_parse_trades_xml_basic():
    xml_text = read_fixture("molit_trades_sample.xml")
    trades = parse_trades_xml(xml_text)

    assert len(trades) == 2
    first = trades[0]
    assert first["deal_date"] == date(2024, 1, 19)
    assert first["property_type"] == "apt"
    assert first["building_name"] == "종로청계힐스테이트"
    assert first["area_m2"] == 84.9478
    assert first["floor"] == 13
    assert first["build_year"] == 2009
    assert first["price_krw"] == 101_300 * 10_000
    assert first["region_code"] == "11110"
    assert first["jibun"] == "766"
    # region_name을 안 주면 estateAgentSggNm(중개업소 소재지, 매물 소재지와 다를 수 있음)에
    # 의존하지 않고 동/지번만으로 주소를 구성한다
    assert first["address"] == "숭인동 766"


def test_parse_trades_xml_with_region_name():
    xml_text = read_fixture("molit_trades_sample.xml")
    trades = parse_trades_xml(xml_text, region_name="서울특별시 종로구")
    assert trades[0]["address"] == "서울특별시 종로구 숭인동 766"


@responses.activate
def test_collect_trades_saves_rows(db_engine, monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy-key")
    responses.add(responses.GET, ENDPOINT, body=read_fixture("molit_trades_sample.xml"), status=200)

    saved = collect_trades(
        region_code="11110",
        start_ymd="202401",
        end_ymd="202401",
        region_name="서울특별시 종로구",
        engine=db_engine,
    )

    assert saved == 2
    with get_session(db_engine) as db:
        assert db.query(Trade).count() == 2


@responses.activate
def test_collect_trades_is_idempotent(db_engine, monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy-key")
    responses.add(responses.GET, ENDPOINT, body=read_fixture("molit_trades_sample.xml"), status=200)

    collect_trades(region_code="11110", start_ymd="202401", end_ymd="202401", engine=db_engine)
    saved_again = collect_trades(region_code="11110", start_ymd="202401", end_ymd="202401", engine=db_engine)

    assert saved_again == 0
    with get_session(db_engine) as db:
        assert db.query(Trade).count() == 2


def test_collect_trades_requires_api_key(db_engine, monkeypatch):
    monkeypatch.delenv("DATA_GO_KR_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        collect_trades(region_code="11110", start_ymd="202401", end_ymd="202401", engine=db_engine)
