"""브이월드(VWorld) 지오코더 — 지번주소 -> 위경도.

API 문서: https://www.vworld.kr/dev/v4dv_geocoderguide2_s001.do
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..config import load_settings
from ..db import GeoCache, Trade, get_session, init_db
from .base import MissingApiKeyError, build_session

ENDPOINT = "https://api.vworld.kr/req/address"


def parse_geocode_response(data: dict) -> tuple[float, float] | None:
    response = data.get("response", {})
    if response.get("status") != "OK":
        return None
    point = response.get("result", {}).get("point", {})
    if "x" not in point or "y" not in point:
        return None
    return float(point["y"]), float(point["x"])  # (lat, lng)


def parse_geocode_response_detailed(data: dict) -> dict | None:
    """좌표뿐 아니라 structure.level4LC(법정동+지번 PNU 유사 코드)까지 뽑는다.

    건축물대장 조회에 필요한 시군구코드/법정동코드/지번을 얻기 위해 쓰인다.
    """
    response = data.get("response", {})
    if response.get("status") != "OK":
        return None
    point = response.get("result", {}).get("point", {})
    if "x" not in point or "y" not in point:
        return None
    structure = response.get("refined", {}).get("structure", {})
    return {
        "lat": float(point["y"]),
        "lng": float(point["x"]),
        "pnu": structure.get("level4LC") or None,
    }


def _request_geocode(address: str, api_key: str, session=None):
    session = session or build_session()
    resp = session.get(
        ENDPOINT,
        params={
            "service": "address",
            "request": "getcoord",
            "version": "2.0",
            "crs": "epsg:4326",
            "address": address,
            "refine": "true",
            "simple": "false",
            "format": "json",
            "type": "parcel",
            "key": api_key,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def geocode_address(address: str, api_key: str, session=None) -> tuple[float, float] | None:
    return parse_geocode_response(_request_geocode(address, api_key, session=session))


def geocode_address_detailed(address: str, api_key: str, session=None) -> dict | None:
    return parse_geocode_response_detailed(_request_geocode(address, api_key, session=session))


def collect_geocodes(engine=None, commit_every: int = 20) -> int:
    """trades 테이블에 있는 주소 중 geocache에 없는 것들을 지오코딩해 저장한다.

    네트워크 오류 등으로 중간에 실패해도 이미 처리한 만큼은 남도록
    `commit_every`건마다 커밋한다 (재실행하면 남은 주소부터 이어서 처리됨).
    지번이 "*"로 마스킹된 주소(단독/다가구 등 개인정보 보호로 일부 데이터에서
    발생)는 애초에 정확한 좌표를 구할 수 없고 VWorld 서버가 이런 입력에
    연결을 끊어버리는 경우가 있어 요청 자체를 건너뛴다.
    """
    settings = load_settings()
    if not settings.vworld_api_key:
        raise MissingApiKeyError("브이월드(VWORLD_API_KEY)")

    engine = engine or init_db()
    session = build_session()
    saved = 0

    with get_session(engine) as db:
        addresses = {
            row[0]
            for row in db.execute(select(Trade.address)).all()
            if row[0]
        }
        cached = {
            row[0] for row in db.execute(select(GeoCache.address)).all()
        }
        todo = sorted(a for a in (addresses - cached) if "*" not in a)

        for i, address in enumerate(todo, start=1):
            coord = geocode_address(address, settings.vworld_api_key, session=session)
            if coord is not None:
                lat, lng = coord
                db.add(GeoCache(address=address, lat=lat, lng=lng, updated_at=datetime.now(timezone.utc)))
                saved += 1
            if i % commit_every == 0:
                db.commit()
        db.commit()

    return saved
