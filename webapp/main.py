"""가격산정 추계 로컬 웹 화면.

실행: uvicorn webapp.main:app --reload --port 8000
"""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from avm.collectors.base import MissingApiKeyError, sanitize_error
from avm.collectors.building_register import (
    EXPOS_GB_EXCLUSIVE,
    fetch_expos_info,
    fetch_title_info,
    lookup_building_spec,
    resolve_pnu,
    suggest_property_type,
)
from avm.collectors.vworld_geocode import geocode_address
from avm.config import load_settings
from avm.db import PROPERTY_TYPE_LABELS, PROPERTY_TYPES, get_engine, init_db
from avm.features import PROPERTY_TYPE_COLUMNS
from avm.model import load_model, predict_one


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="AVM 가격산정 추계", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def find_nearby_trades(engine, lat: float, lng: float, limit: int = 8, radius_km: float = 3.0) -> list[dict]:
    if lat is None or lng is None:
        return []

    query = text(
        """
        SELECT t.property_type, t.building_name, t.address, t.deal_date, t.area_m2, t.floor, t.price_krw,
               g.lat, g.lng
        FROM trades t
        JOIN geocache g ON g.address = t.address
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()

    scored = []
    for row in rows:
        dist = haversine_km(lat, lng, row["lat"], row["lng"])
        if dist <= radius_km:
            scored.append((dist, row))
    scored.sort(key=lambda pair: pair[0])

    return [
        {
            "distance_km": round(dist, 2),
            "property_type_label": PROPERTY_TYPE_LABELS.get(row["property_type"], row["property_type"]),
            "building_name": row["building_name"],
            "address": row["address"],
            "deal_date": str(row["deal_date"]),
            "area_m2": row["area_m2"],
            "floor": row["floor"],
            "price_krw": row["price_krw"],
        }
        for dist, row in scored[:limit]
    ]


def resolve_coordinates(engine, address: str) -> tuple[float, float] | None:
    """geocache에 있으면 그 값을 쓰고, 없으면 VWorld 키가 있을 때만 실시간 조회한다."""
    with engine.connect() as conn:
        row = conn.execute(text("SELECT lat, lng FROM geocache WHERE address = :a"), {"a": address}).first()
    if row is not None:
        return (row[0], row[1])

    settings = load_settings()
    if not settings.vworld_api_key:
        return None
    return geocode_address(address, settings.vworld_api_key)


def _build_address(region_name: str, dong: str, jibun: str) -> str:
    return " ".join(part for part in [region_name.strip(), dong.strip(), jibun.strip()] if part).strip()


@app.get("/api/buildings")
async def api_buildings(region_name: str = "", dong: str = "", jibun: str = ""):
    """지번 주소로 건축물대장 표제부를 조회해 건물동 목록(+용도 추정)을 돌려준다."""
    address = _build_address(region_name, dong, jibun)
    if not address:
        return JSONResponse({"error": "주소를 입력해 주세요."}, status_code=400)

    settings = load_settings()
    if not settings.vworld_api_key or not settings.data_go_kr_api_key:
        return JSONResponse({"error": "VWorld/공공데이터포털 API 키가 설정되지 않았습니다."}, status_code=400)

    lookup = resolve_pnu(address, settings.vworld_api_key)
    if lookup.pnu is None:
        return JSONResponse({"error": lookup.warning or "주소를 찾지 못했습니다."}, status_code=404)

    try:
        titles = fetch_title_info(lookup.pnu, settings.data_go_kr_api_key)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": sanitize_error(exc)}, status_code=502)

    buildings = [
        {
            "dong_name": t["dong_name"],
            "main_purpose": t["etc_purpose"] or t["main_purpose"],
            "suggested_type": suggest_property_type(t["main_purpose"], t["etc_purpose"]),
        }
        for t in titles
        if t["dong_name"]
    ]
    return JSONResponse({"buildings": buildings})


@app.get("/api/units")
async def api_units(region_name: str = "", dong: str = "", jibun: str = "", building_dong: str = ""):
    """선택한 건물동의 전유부(호실별 전용면적/층) 목록을 돌려준다."""
    address = _build_address(region_name, dong, jibun)
    if not address:
        return JSONResponse({"error": "주소를 입력해 주세요."}, status_code=400)

    settings = load_settings()
    if not settings.vworld_api_key or not settings.data_go_kr_api_key:
        return JSONResponse({"error": "VWorld/공공데이터포털 API 키가 설정되지 않았습니다."}, status_code=400)

    lookup = resolve_pnu(address, settings.vworld_api_key)
    if lookup.pnu is None:
        return JSONResponse({"error": lookup.warning or "주소를 찾지 못했습니다."}, status_code=404)

    try:
        units = fetch_expos_info(lookup.pnu, settings.data_go_kr_api_key)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": sanitize_error(exc)}, status_code=502)

    norm_target = building_dong.strip().rstrip("동") if building_dong else ""
    result = [
        {"ho_name": u["ho_name"], "area_m2": u["exclusive_area"], "floor": u["floor"]}
        for u in units
        if u["expos_gb"] == EXPOS_GB_EXCLUSIVE
        and u["ho_name"]
        and (not norm_target or u["dong_name"].rstrip("동") == norm_target)
    ]
    return JSONResponse({"units": result})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"property_types": PROPERTY_TYPES, "labels": PROPERTY_TYPE_LABELS},
    )


@app.post("/estimate", response_class=HTMLResponse)
async def estimate(
    request: Request,
    property_type: str = Form(...),
    region_name: str = Form(""),
    dong: str = Form(""),
    jibun: str = Form(""),
    building_dong: str = Form(""),
    ho: str = Form(""),
    area_m2: float | None = Form(None),
    floor: int | None = Form(None),
    build_year: int | None = Form(None),
):
    address = " ".join(part for part in [region_name.strip(), dong.strip(), jibun.strip()] if part).strip()
    engine = get_engine()

    error = None
    lat = lng = None
    price = None
    comparables: list[dict] = []
    auto_note = None
    auto_filled = False

    if not address:
        error = "지역명/동/지번 중 최소 하나 이상을 입력해 주소를 구성해 주세요."
    elif area_m2 is None or build_year is None:
        # 면적/건축년도 중 하나라도 비어 있으면 건축물대장 자동조회를 시도한다.
        settings = load_settings()
        if not settings.data_go_kr_api_key:
            error = "면적/건축년도를 비워두면 건축물대장에서 자동조회하는데, 공공데이터포털 키가 없어 불가능합니다. 값을 직접 입력해 주세요."
        else:
            try:
                spec = lookup_building_spec(address, dong_name=building_dong.strip(), ho_name=ho.strip())
            except MissingApiKeyError as exc:
                spec = None
                error = str(exc)
            if spec is not None:
                lat, lng = spec["lat"], spec["lng"]
                auto_note = spec["warning"]
                if lat is None:
                    error = auto_note or "주소 좌표를 찾지 못했습니다."
                else:
                    if area_m2 is None and spec["area_m2"] is not None:
                        area_m2 = spec["area_m2"]
                        auto_filled = True
                    if floor is None and spec["floor"] is not None:
                        floor = spec["floor"]
                        auto_filled = True
                    if build_year is None and spec["build_year"] is not None:
                        build_year = spec["build_year"]
                        auto_filled = True
                    if area_m2 is None or build_year is None:
                        error = (auto_note + " " if auto_note else "") + "면적/건축년도를 자동으로 채우지 못했습니다. 직접 입력해 주세요."
    else:
        try:
            coord = resolve_coordinates(engine, address)
        except Exception as exc:  # noqa: BLE001 - 사용자에게 원인을 그대로 보여주기 위함
            coord = None
            error = f"좌표 조회 중 오류가 발생했습니다: {sanitize_error(exc)}"
        if coord is None and error is None:
            error = "입력한 주소의 좌표를 찾지 못했습니다. 주소를 더 구체적으로 입력해보세요."
        elif coord is not None:
            lat, lng = coord

    model_bundle = None
    if not error:
        try:
            model_bundle = load_model()
        except FileNotFoundError:
            error = "학습된 모델이 없습니다. 먼저 `python -m avm.cli train`으로 모델을 학습해 주세요."

    if not error and model_bundle is not None:
        today = date.today()
        features = {
            "area_m2": area_m2,
            "floor": floor,
            "age": today.year - build_year,
            "lat": lat,
            "lng": lng,
            "base_rate": None,
            "deal_year": today.year,
            "deal_month": today.month,
        }
        for t, col in zip(PROPERTY_TYPES, PROPERTY_TYPE_COLUMNS):
            features[col] = 1 if t == property_type else 0

        price = predict_one(model_bundle, features)
        comparables = find_nearby_trades(engine, lat, lng)

    return templates.TemplateResponse(
        request=request,
        name="result.html",
        context={
            "error": error,
            "price": price,
            "address": address,
            "lat": lat,
            "lng": lng,
            "comparables": comparables,
            "property_type_label": PROPERTY_TYPE_LABELS.get(property_type, property_type),
            "area_m2": area_m2,
            "floor": floor,
            "build_year": build_year,
            "auto_filled": auto_filled,
            "auto_note": auto_note,
        },
    )
