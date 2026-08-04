"""한국은행 ECOS — 기준금리 월별 시계열.

API 문서: https://ecos.bok.or.kr/api/#/
통계코드(stat_code)/항목코드(item_code)는 ECOS Open API의 "통계코드 검색"에서
직접 확인 후 필요시 바꿔서 사용한다. 기본값은 한국은행 기준금리(722Y001/0101000).
"""

from __future__ import annotations

from ..config import load_settings
from ..db import BaseRate, get_session, init_db
from .base import MissingApiKeyError, build_session

ENDPOINT_TEMPLATE = (
    "https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/1000/"
    "{stat_code}/{cycle}/{start}/{end}/{item_code}"
)

DEFAULT_STAT_CODE = "722Y001"
DEFAULT_ITEM_CODE = "0101000"
DEFAULT_CYCLE = "M"


def parse_ecos_response(data: dict) -> list[dict]:
    result = data.get("StatisticSearch")
    if result is None:
        error = data.get("RESULT", {})
        raise RuntimeError(f"ECOS API 오류: {error.get('MESSAGE', data)}")

    rows = result.get("row", [])
    parsed = []
    for row in rows:
        time_raw = row["TIME"]  # "YYYYMM"
        month = f"{time_raw[:4]}-{time_raw[4:6]}"
        parsed.append({"month": month, "base_rate": float(row["DATA_VALUE"])})
    return parsed


def fetch_rates(
    api_key: str,
    start: str,
    end: str,
    stat_code: str = DEFAULT_STAT_CODE,
    item_code: str = DEFAULT_ITEM_CODE,
    cycle: str = DEFAULT_CYCLE,
    session=None,
) -> list[dict]:
    session = session or build_session()
    url = ENDPOINT_TEMPLATE.format(
        api_key=api_key,
        stat_code=stat_code,
        cycle=cycle,
        start=start,
        end=end,
        item_code=item_code,
    )
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    return parse_ecos_response(resp.json())


def collect_rates(start: str, end: str, engine=None) -> int:
    """start/end는 "YYYYMM" 형식. 기준금리를 조회해 DB에 저장한다."""
    settings = load_settings()
    if not settings.ecos_api_key:
        raise MissingApiKeyError("한국은행 ECOS(ECOS_API_KEY)")

    engine = engine or init_db()
    rates = fetch_rates(settings.ecos_api_key, start, end)

    saved = 0
    with get_session(engine) as db:
        for r in rates:
            existing = db.get(BaseRate, r["month"])
            if existing:
                existing.base_rate = r["base_rate"]
            else:
                db.add(BaseRate(**r))
                saved += 1
        db.commit()

    return saved
