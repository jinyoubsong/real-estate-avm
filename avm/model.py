from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, root_mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline

from .config import PROJECT_ROOT
from .features import FEATURE_COLUMNS, TARGET_COLUMN

MODELS_DIR = PROJECT_ROOT / "models"


def _build_candidates() -> dict:
    return {
        "linear_baseline": make_pipeline(SimpleImputer(strategy="mean"), LinearRegression()),
        "hist_gradient_boosting": HistGradientBoostingRegressor(random_state=42),
    }


def _evaluate(model, X_test, y_test) -> dict:
    pred = model.predict(X_test)
    return {
        "mae": float(mean_absolute_error(y_test, pred)),
        "rmse": float(root_mean_squared_error(y_test, pred)),
        "mape": float(mean_absolute_percentage_error(y_test, pred)),
    }


def train(df: pd.DataFrame, test_size: float = 0.2, random_state: int = 42) -> dict:
    """후보 모델들을 학습·평가하고, 가장 좋은(MAE 기준) 모델을 선택해 반환한다.

    아직 수집되지 않아 전부 결측(NaN)인 피처 열은 학습에서 자동으로 제외한다
    (예: ECOS 키가 없어 base_rate를 아직 수집하지 않은 경우).
    """
    df = df.dropna(subset=[TARGET_COLUMN])
    if len(df) < 20:
        raise ValueError(f"학습 데이터가 너무 적습니다 ({len(df)}건). 최소 20건 이상 필요합니다.")

    usable_columns = [c for c in FEATURE_COLUMNS if df[c].notna().any()]
    dropped_columns = [c for c in FEATURE_COLUMNS if c not in usable_columns]

    X = df[usable_columns]
    y = df[TARGET_COLUMN]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=random_state)

    results = {}
    for name, model in _build_candidates().items():
        model.fit(X_train, y_train)
        results[name] = {"model": model, "metrics": _evaluate(model, X_test, y_test)}

    best_name = min(results, key=lambda n: results[n]["metrics"]["mae"])
    return {
        "best_name": best_name,
        "best_model": results[best_name]["model"],
        "all_metrics": {name: r["metrics"] for name, r in results.items()},
        "n_train": len(X_train),
        "n_test": len(X_test),
        "feature_columns": usable_columns,
        "dropped_columns": dropped_columns,
    }


def save_model(result: dict, name: str = "avm_model") -> Path:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{name}.joblib"
    report_path = MODELS_DIR / f"{name}_report.json"

    bundle = {"model": result["best_model"], "feature_columns": result["feature_columns"]}
    joblib.dump(bundle, model_path)
    report_path.write_text(
        json.dumps(
            {
                "best_name": result["best_name"],
                "all_metrics": result["all_metrics"],
                "n_train": result["n_train"],
                "n_test": result["n_test"],
                "feature_columns": result["feature_columns"],
                "dropped_columns": result["dropped_columns"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return model_path


def load_model(name: str = "avm_model") -> dict:
    return joblib.load(MODELS_DIR / f"{name}.joblib")


def load_report(name: str = "avm_model") -> dict | None:
    """학습 시 저장된 리포트(모델 종류/정확도/학습건수 등)를 읽는다. 없으면 None."""
    report_path = MODELS_DIR / f"{name}_report.json"
    if not report_path.exists():
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))


def predict_one(bundle: dict, features: dict) -> float:
    columns = bundle["feature_columns"]
    row = pd.DataFrame([{col: features.get(col) for col in columns}])
    return float(bundle["model"].predict(row)[0])
