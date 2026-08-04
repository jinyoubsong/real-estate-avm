from datetime import date

from fastapi.testclient import TestClient

from avm import db as db_module
from avm import model as model_module
from avm.db import GeoCache, Trade, get_session
from avm.model import save_model, train
from test_model import _make_synthetic_df

SEEDED_ADDRESS = "서울특별시 종로구 숭인동 766"


def _seed_db(engine):
    with get_session(engine) as db:
        db.add(
            Trade(
                property_type="apt",
                region_code="11110",
                deal_date=date(2024, 1, 15),
                building_name="종로청계힐스테이트",
                jibun="766",
                area_m2=84.93,
                floor=10,
                build_year=2009,
                price_krw=1_000_000_000,
                address=SEEDED_ADDRESS,
            )
        )
        db.add(GeoCache(address=SEEDED_ADDRESS, lat=37.5759, lng=127.0212))
        db.commit()


def _train_and_save():
    result = train(_make_synthetic_df())
    save_model(result, name="avm_model")


def _make_client(tmp_path, monkeypatch, *, with_model: bool, with_data: bool) -> TestClient:
    db_path = tmp_path / "webapp_test.db"
    monkeypatch.setenv("AVM_DB_PATH", str(db_path))
    monkeypatch.delenv("VWORLD_API_KEY", raising=False)
    # 실제 프로젝트의 models/ 디렉터리를 절대 건드리지 않도록 항상 격리한다
    # (모델이 없어야 하는 테스트가 실제 학습된 모델을 주워 쓰는 걸 방지)
    monkeypatch.setattr(model_module, "MODELS_DIR", tmp_path / "models")

    engine = db_module.get_engine(db_path=db_path)
    db_module.init_db(engine)
    if with_data:
        _seed_db(engine)
    if with_model:
        _train_and_save()

    from webapp.main import app

    return TestClient(app)


def test_index_renders_form(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, with_model=False, with_data=False)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "부동산 가격산정 추계" in resp.text
    assert "property_type" in resp.text


def test_estimate_without_model_shows_friendly_error(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, with_model=False, with_data=True)
    resp = client.post(
        "/estimate",
        data={
            "property_type": "apt",
            "region_name": "서울특별시 종로구",
            "dong": "숭인동",
            "jibun": "766",
            "area_m2": "84.93",
            "floor": "10",
            "build_year": "2009",
        },
    )
    assert resp.status_code == 200
    assert "학습된 모델이 없습니다" in resp.text


def test_estimate_with_unresolvable_address_shows_error(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, with_model=True, with_data=True)
    resp = client.post(
        "/estimate",
        data={
            "property_type": "apt",
            "region_name": "존재하지않는시",
            "dong": "존재하지않는동",
            "jibun": "0-0",
            "area_m2": "84.93",
            "floor": "10",
            "build_year": "2009",
        },
    )
    assert resp.status_code == 200
    assert "좌표를 찾지 못했습니다" in resp.text


def test_estimate_success_shows_price_and_comparables(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, with_model=True, with_data=True)
    resp = client.post(
        "/estimate",
        data={
            "property_type": "apt",
            "region_name": "서울특별시 종로구",
            "dong": "숭인동",
            "jibun": "766",
            "area_m2": "84.93",
            "floor": "10",
            "build_year": "2009",
        },
    )
    assert resp.status_code == 200
    assert "학습된 모델이 없습니다" not in resp.text
    assert "좌표를 찾지 못했습니다" not in resp.text
    assert "원" in resp.text
    assert "종로청계힐스테이트" in resp.text  # 인근 비교 사례에 표시
