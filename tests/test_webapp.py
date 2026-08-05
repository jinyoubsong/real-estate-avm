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


def test_estimate_with_manual_specs_skips_building_register_lookup(tmp_path, monkeypatch):
    """면적/건축년도를 모두 입력하면 건축물대장 자동조회를 시도하지 않아야 한다."""
    import webapp.main as webapp_main

    def _boom(*args, **kwargs):
        raise AssertionError("lookup_building_spec은 호출되면 안 됩니다")

    client = _make_client(tmp_path, monkeypatch, with_model=True, with_data=True)
    monkeypatch.setattr(webapp_main, "lookup_building_spec", _boom)

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
    assert "원" in resp.text


def test_estimate_auto_lookup_fills_missing_specs(tmp_path, monkeypatch):
    import webapp.main as webapp_main

    client = _make_client(tmp_path, monkeypatch, with_model=True, with_data=True)
    monkeypatch.setattr(
        webapp_main,
        "lookup_building_spec",
        lambda address, dong_name="", ho_name="": {
            "area_m2": 84.9478,
            "floor": 13,
            "build_year": 2009,
            "lat": 37.5759,
            "lng": 127.0212,
            "warning": None,
        },
    )

    resp = client.post(
        "/estimate",
        data={
            "property_type": "apt",
            "region_name": "서울특별시 종로구",
            "dong": "숭인동",
            "jibun": "766",
            "building_dong": "104동",
            "ho": "1301호",
        },
    )
    assert resp.status_code == 200
    assert "원" in resp.text
    assert "자동조회" in resp.text
    assert "84.9478" in resp.text


def test_estimate_auto_lookup_partial_failure_shows_error(tmp_path, monkeypatch):
    import webapp.main as webapp_main

    client = _make_client(tmp_path, monkeypatch, with_model=True, with_data=True)
    monkeypatch.setattr(
        webapp_main,
        "lookup_building_spec",
        lambda address, dong_name="", ho_name="": {
            "area_m2": None,
            "floor": None,
            "build_year": None,
            "lat": 37.5759,
            "lng": 127.0212,
            "warning": "동/호에 해당하는 전유부 정보를 찾지 못해 면적/층은 직접 입력해 주세요.",
        },
    )

    resp = client.post(
        "/estimate",
        data={
            "property_type": "apt",
            "region_name": "서울특별시 종로구",
            "dong": "숭인동",
            "jibun": "766",
        },
    )
    assert resp.status_code == 200
    assert "직접 입력해 주세요" in resp.text


def test_api_buildings_missing_address_returns_400(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, with_model=False, with_data=False)
    resp = client.get("/api/buildings")
    assert resp.status_code == 400


def test_api_buildings_success_returns_suggested_type(tmp_path, monkeypatch):
    import webapp.main as webapp_main
    from avm.collectors.building_register import AddressLookup, Pnu

    client = _make_client(tmp_path, monkeypatch, with_model=False, with_data=False)
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    pnu = Pnu(sigungu_cd="11110", bjdong_cd="17500", plat_gb_cd="0", bun="0766", ji="0000")
    monkeypatch.setattr(
        webapp_main, "resolve_pnu", lambda address, key: AddressLookup(pnu, 37.5759, 127.0212, None)
    )
    monkeypatch.setattr(
        webapp_main,
        "fetch_title_info",
        lambda pnu, key: [
            {"dong_name": "104동", "main_purpose": "공동주택", "etc_purpose": "아파트", "ground_floors": 13},
        ],
    )

    resp = client.get(
        "/api/buildings",
        params={"region_name": "서울특별시 종로구", "dong": "숭인동", "jibun": "766"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["buildings"] == [{"dong_name": "104동", "main_purpose": "아파트", "suggested_type": "apt"}]


def test_api_buildings_address_not_found_returns_404(tmp_path, monkeypatch):
    import webapp.main as webapp_main
    from avm.collectors.building_register import AddressLookup

    client = _make_client(tmp_path, monkeypatch, with_model=False, with_data=False)
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    monkeypatch.setattr(
        webapp_main, "resolve_pnu", lambda address, key: AddressLookup(None, None, None, "주소 좌표/코드를 찾지 못했습니다.")
    )

    resp = client.get(
        "/api/buildings",
        params={"region_name": "존재하지않는시", "dong": "존재하지않는동", "jibun": "0-0"},
    )
    assert resp.status_code == 404


def test_api_units_filters_exclusive_area_and_dong(tmp_path, monkeypatch):
    import webapp.main as webapp_main
    from avm.collectors.building_register import AddressLookup, Pnu

    client = _make_client(tmp_path, monkeypatch, with_model=False, with_data=False)
    monkeypatch.setenv("VWORLD_API_KEY", "dummy")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "dummy")
    pnu = Pnu(sigungu_cd="11110", bjdong_cd="17500", plat_gb_cd="0", bun="0766", ji="0000")
    monkeypatch.setattr(
        webapp_main, "resolve_pnu", lambda address, key: AddressLookup(pnu, 37.5759, 127.0212, None)
    )
    monkeypatch.setattr(
        webapp_main,
        "fetch_expos_info",
        lambda pnu, key: [
            {"dong_name": "104동", "ho_name": "102", "exclusive_area": 59.9426, "floor": 1, "expos_gb": "1"},
            {"dong_name": "104동", "ho_name": "102", "exclusive_area": 18.38, "floor": 0, "expos_gb": "2"},
            {"dong_name": "103동", "ho_name": "201", "exclusive_area": 84.9, "floor": 2, "expos_gb": "1"},
        ],
    )

    resp = client.get(
        "/api/units",
        params={"region_name": "서울특별시 종로구", "dong": "숭인동", "jibun": "766", "building_dong": "104동"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["units"] == [{"ho_name": "102", "area_m2": 59.9426, "floor": 1}]
