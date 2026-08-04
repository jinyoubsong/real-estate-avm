from __future__ import annotations

import pandas as pd

from .db import PROPERTY_TYPES, get_engine

PROPERTY_TYPE_COLUMNS = [f"is_{t}" for t in PROPERTY_TYPES]
FEATURE_COLUMNS = [
    "area_m2",
    "floor",
    "age",
    "lat",
    "lng",
    "base_rate",
    "deal_year",
    "deal_month",
    *PROPERTY_TYPE_COLUMNS,
]
TARGET_COLUMN = "price_krw"


def build_feature_frame(engine=None) -> pd.DataFrame:
    """trades + geocache + rates 를 조인해 학습용 피처 데이터프레임을 만든다.

    좌표(lat/lng)나 기준금리가 아직 수집되지 않은 행도 남겨두되(NaN),
    모델 학습 시점에 결측 처리한다.
    """
    engine = engine or get_engine()

    trades = pd.read_sql("SELECT * FROM trades", engine, parse_dates=["deal_date"])
    if trades.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS + [TARGET_COLUMN])

    geocache = pd.read_sql("SELECT * FROM geocache", engine)
    rates = pd.read_sql("SELECT * FROM rates", engine)

    df = trades.merge(geocache[["address", "lat", "lng"]], on="address", how="left")

    df["deal_year"] = df["deal_date"].dt.year
    df["deal_month"] = df["deal_date"].dt.month
    df["month"] = df["deal_date"].dt.strftime("%Y-%m")
    df = df.merge(rates[["month", "base_rate"]], on="month", how="left")

    df["age"] = df["deal_year"] - df["build_year"]

    for t, col in zip(PROPERTY_TYPES, PROPERTY_TYPE_COLUMNS):
        df[col] = (df["property_type"] == t).astype(int)

    return df[["id", "address", "property_type", *FEATURE_COLUMNS, TARGET_COLUMN]]
