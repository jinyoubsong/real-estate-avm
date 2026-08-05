import random

import pandas as pd
import pytest

from avm import model as model_module
from avm.db import PROPERTY_TYPES
from avm.features import FEATURE_COLUMNS, PROPERTY_TYPE_COLUMNS, TARGET_COLUMN
from avm.model import load_model, load_report, predict_one, save_model, train


def _make_synthetic_df(n=60, with_missing=True) -> pd.DataFrame:
    random.seed(0)
    rows = []
    for i in range(n):
        area = random.uniform(40, 130)
        floor = random.randint(1, 20)
        age = random.randint(0, 30)
        lat = 37.5 + random.uniform(-0.05, 0.05)
        lng = 127.0 + random.uniform(-0.05, 0.05)
        base_rate = 3.0 + random.uniform(-0.5, 0.5)
        price = 10_000_000 * area * (1 - age * 0.01) + random.uniform(-5_000_000, 5_000_000)

        if with_missing and i % 10 == 0:
            lat = None
            lng = None
        if with_missing and i % 15 == 0:
            base_rate = None

        row = {
            "area_m2": area,
            "floor": floor,
            "age": age,
            "lat": lat,
            "lng": lng,
            "base_rate": base_rate,
            "deal_year": 2024,
            "deal_month": (i % 12) + 1,
            TARGET_COLUMN: price,
        }
        chosen_type = PROPERTY_TYPES[i % len(PROPERTY_TYPES)]
        for t, col in zip(PROPERTY_TYPES, PROPERTY_TYPE_COLUMNS):
            row[col] = int(t == chosen_type)
        rows.append(row)
    return pd.DataFrame(rows)


def test_train_selects_best_model_and_reports_metrics():
    df = _make_synthetic_df()
    result = train(df)

    assert result["best_name"] in {"linear_baseline", "hist_gradient_boosting"}
    assert set(result["all_metrics"]) == {"linear_baseline", "hist_gradient_boosting"}
    for metrics in result["all_metrics"].values():
        assert metrics["mae"] >= 0
        assert metrics["rmse"] >= 0
        assert metrics["mape"] >= 0
    assert result["n_train"] + result["n_test"] == len(df)


def test_train_raises_when_too_few_rows():
    df = _make_synthetic_df(n=10)
    with pytest.raises(ValueError):
        train(df)


def test_train_drops_entirely_missing_columns():
    """base_rate처럼 아직 한 건도 수집되지 않아 전부 NaN인 피처는 학습에서 제외되어야 한다.

    (HistGradientBoostingRegressor는 전부 결측인 컬럼이 있으면 예외를 던진다.)
    """
    df = _make_synthetic_df(with_missing=False)
    df["base_rate"] = None
    df["lat"] = None
    df["lng"] = None

    result = train(df)

    assert set(result["dropped_columns"]) == {"base_rate", "lat", "lng"}
    assert "base_rate" not in result["feature_columns"]


def test_save_and_load_model_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(model_module, "MODELS_DIR", tmp_path)
    df = _make_synthetic_df()
    result = train(df)
    path = save_model(result, name="test_model")

    assert path.exists()
    assert (tmp_path / "test_model_report.json").exists()

    loaded = load_model(name="test_model")
    price = predict_one(loaded, {col: 50.0 for col in FEATURE_COLUMNS})
    assert isinstance(price, float)

    report = load_report(name="test_model")
    assert report["best_name"] == result["best_name"]
    assert report["n_train"] == result["n_train"]
    assert set(report["all_metrics"]) == {"linear_baseline", "hist_gradient_boosting"}


def test_load_report_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(model_module, "MODELS_DIR", tmp_path)
    assert load_report(name="does_not_exist") is None
