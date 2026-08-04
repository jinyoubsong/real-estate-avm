from datetime import date

from avm.db import BaseRate, GeoCache, Trade, get_session
from avm.features import FEATURE_COLUMNS, TARGET_COLUMN, build_feature_frame


def _seed(engine, *, with_geo=True, with_rate=True):
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
        if with_geo:
            db.add(GeoCache(address="서울특별시 종로구 종로동 123-4", lat=37.5665, lng=126.978))
        if with_rate:
            db.add(BaseRate(month="2024-01", base_rate=3.5))
        db.commit()


def test_build_feature_frame_joins_all_sources(db_engine):
    _seed(db_engine)
    df = build_feature_frame(db_engine)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["age"] == 2024 - 2001
    assert row["lat"] == 37.5665
    assert row["lng"] == 126.978
    assert row["base_rate"] == 3.5
    assert row["deal_year"] == 2024
    assert row["deal_month"] == 1
    assert row[TARGET_COLUMN] == 2_500_000_000
    for col in FEATURE_COLUMNS:
        assert col in df.columns


def test_build_feature_frame_handles_missing_geo_and_rate(db_engine):
    _seed(db_engine, with_geo=False, with_rate=False)
    df = build_feature_frame(db_engine)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["lat"] != row["lat"]  # NaN
    assert row["base_rate"] != row["base_rate"]  # NaN


def test_build_feature_frame_empty_db(db_engine):
    df = build_feature_frame(db_engine)
    assert df.empty
