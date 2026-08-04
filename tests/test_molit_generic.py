from datetime import date

import pytest
import responses

from avm.collectors.base import MissingApiKeyError
from avm.collectors.molit_generic import TYPE_CONFIGS, collect_trades, parse_trades_xml
from avm.db import Trade, get_session
from conftest import read_fixture


def test_parse_trades_xml_apt_config_matches_real_schema():
    """apt 설정은 molit_trades.py와 동일한 실제 검증된 스키마를 써야 한다."""
    xml_text = read_fixture("molit_trades_sample.xml")
    trades = parse_trades_xml(xml_text, TYPE_CONFIGS["apt"])

    assert len(trades) == 2
    assert trades[0]["property_type"] == "apt"
    assert trades[0]["building_name"] == "종로청계힐스테이트"


def test_parse_trades_xml_rh_config():
    """연립다세대 설정은 문서 기반 추정 스키마 — 필드명은 실제 승인 후 재검증 필요."""
    xml_text = read_fixture("molit_rh_sample.xml")
    trades = parse_trades_xml(xml_text, TYPE_CONFIGS["rh"])

    assert len(trades) == 1
    first = trades[0]
    assert first["property_type"] == "rh"
    assert first["building_name"] == "행복다세대"
    assert first["deal_date"] == date(2024, 3, 5)
    assert first["area_m2"] == 45.2
    assert first["price_krw"] == 35_000 * 10_000
    assert first["address"] == "서울 종로구 창신동 12-3"


def test_parse_trades_xml_unknown_field_defaults_gracefully():
    """설정에 없는/응답에 없는 필드는 예외 대신 빈 값/0으로 처리되어야 한다."""
    xml_text = read_fixture("molit_rh_sample.xml")
    # sh 설정(totalFloorAr, houseType)을 rh 응답에 억지로 적용 — 필드가 없으므로 0/빈 문자열
    trades = parse_trades_xml(xml_text, TYPE_CONFIGS["sh"])

    assert len(trades) == 1
    assert trades[0]["area_m2"] == 0
    assert trades[0]["building_name"] == ""


@responses.activate
def test_collect_trades_unknown_type_raises():
    with pytest.raises(ValueError):
        collect_trades("unknown_type", "11110", "202401", "202401")


@responses.activate
def test_collect_trades_saves_rh_rows(db_engine, monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy-key")
    responses.add(
        responses.GET,
        TYPE_CONFIGS["rh"].endpoint,
        body=read_fixture("molit_rh_sample.xml"),
        status=200,
    )

    saved = collect_trades("rh", "11110", "202401", "202401", engine=db_engine)

    assert saved == 1
    with get_session(db_engine) as db:
        row = db.query(Trade).filter_by(property_type="rh").first()
        assert row is not None
        assert row.building_name == "행복다세대"


def test_collect_trades_requires_api_key(db_engine, monkeypatch):
    monkeypatch.delenv("DATA_GO_KR_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        collect_trades("rh", "11110", "202401", "202401", engine=db_engine)
