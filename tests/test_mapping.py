from datetime import date

from avm.db import GeoCache, Trade, get_session
from avm.mapping import build_map_html


def _seed(engine):
    with get_session(engine) as db:
        db.add(
            Trade(
                region_code="11110",
                deal_date=date(2024, 1, 15),
                apt_name="테스트아파트",
                jibun="123-4",
                area_m2=84.93,
                floor=10,
                build_year=2001,
                price_krw=2_500_000_000,
                address="서울특별시 종로구 종로동 123-4",
            )
        )
        db.add(GeoCache(address="서울특별시 종로구 종로동 123-4", lat=37.5665, lng=126.978))
        db.commit()


def test_build_map_html_includes_points(db_engine):
    _seed(db_engine)
    html = build_map_html(db_engine)

    assert "<!DOCTYPE html>" in html
    assert "거래 1건 표시" in html
    assert "테스트아파트" in html
    assert "37.5665" in html


def test_build_map_html_handles_empty_db(db_engine):
    html = build_map_html(db_engine)
    assert "거래 0건 표시" in html
    assert "37.5665" in html  # 서울시청 기본 중심좌표
