"""국토교통부 실거래가 수집 공통 로직.

data.go.kr의 아파트/연립다세대/단독다가구/오피스텔 매매 실거래자료는 서로
비슷하지만 완전히 같지는 않은 XML 스키마를 쓴다. 유형별 endpoint와 필드명만
`MolitTypeConfig`로 떼어내고, 파싱/저장 로직은 이 모듈에서 공유한다.

주의: rh/sh/offi 설정의 필드명은 공개 문서·사례를 근거로 한 최선 추정치이며,
아파트(apt)처럼 실제 승인된 키로 호출해 확인하기 전까지는 미확정이다.
해당 유형 활용신청이 승인되면 실제 응답을 보고 `TYPE_CONFIGS`를 보정해야 한다.
필드가 실제로 없으면 빈 문자열/0으로 채워질 뿐 예외는 나지 않는다(파서가 관대함).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from xml.etree import ElementTree

from ..config import load_settings
from ..db import Trade, get_session, init_db
from .base import MissingApiKeyError, build_session


@dataclass(frozen=True)
class MolitTypeConfig:
    property_type: str
    label: str
    endpoint: str
    name_field: str  # 건물/주택 이름 필드 (없는 유형은 빈 문자열 처리됨)
    area_field: str  # 면적 필드 (전용면적 또는 연면적 등)


TYPE_CONFIGS: dict[str, MolitTypeConfig] = {
    "apt": MolitTypeConfig(
        property_type="apt",
        label="아파트",
        endpoint="https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
        name_field="aptNm",
        area_field="excluUseAr",
    ),
    "rh": MolitTypeConfig(
        property_type="rh",
        label="연립다세대",
        endpoint="https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
        name_field="mhouseNm",
        area_field="excluUseAr",
    ),
    "sh": MolitTypeConfig(
        property_type="sh",
        label="단독/다가구",
        endpoint="https://apis.data.go.kr/1613000/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
        name_field="houseType",
        area_field="totalFloorAr",
    ),
    "offi": MolitTypeConfig(
        property_type="offi",
        label="오피스텔",
        endpoint="https://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
        name_field="offiNm",
        area_field="excluUseAr",
    ),
}


def _text(item: ElementTree.Element, tag: str, default: str = "") -> str:
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else default


def parse_trades_xml(xml_text: str, config: MolitTypeConfig, region_name: str = "") -> list[dict]:
    root = ElementTree.fromstring(xml_text)

    header_code = root.findtext("./header/resultCode")
    if header_code not in (None, "00", "000"):
        msg = root.findtext("./header/resultMsg", default="알 수 없는 오류")
        raise RuntimeError(f"국토교통부 API 오류 [{header_code}]: {msg}")

    trades = []
    for item in root.findall("./body/items/item"):
        price_manwon = _text(item, "dealAmount").replace(",", "").strip()
        if not price_manwon:
            continue
        year = int(_text(item, "dealYear"))
        month = int(_text(item, "dealMonth"))
        day = int(_text(item, "dealDay"))
        dong = _text(item, "umdNm")
        jibun = _text(item, "jibun")
        sgg_name = region_name or _text(item, "estateAgentSggNm")
        address = " ".join(part for part in [sgg_name, dong, jibun] if part).strip()

        trades.append(
            {
                "property_type": config.property_type,
                "region_code": _text(item, "sggCd"),
                "deal_date": date(year, month, day),
                "building_name": _text(item, config.name_field),
                "jibun": jibun,
                "area_m2": float(_text(item, config.area_field, "0") or 0),
                "floor": int(_text(item, "floor", "0") or 0),
                "build_year": int(_text(item, "buildYear", "0") or 0),
                "price_krw": int(price_manwon) * 10_000,
                "address": address,
            }
        )
    return trades


def fetch_trades_page(
    config: MolitTypeConfig,
    region_code: str,
    deal_ymd: str,
    api_key: str,
    page_no: int = 1,
    num_of_rows: int = 1000,
    session=None,
) -> str:
    session = session or build_session()
    resp = session.get(
        config.endpoint,
        params={
            "serviceKey": api_key,
            "LAWD_CD": region_code,
            "DEAL_YMD": deal_ymd,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.text


def _month_range(start_ymd: str, end_ymd: str) -> list[str]:
    start_year, start_month = int(start_ymd[:4]), int(start_ymd[4:6])
    end_year, end_month = int(end_ymd[:4]), int(end_ymd[4:6])

    months = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def collect_trades(
    property_type: str,
    region_code: str,
    start_ymd: str,
    end_ymd: str,
    region_name: str = "",
    engine=None,
) -> int:
    """지정 유형·기간의 실거래가를 수집해 DB에 저장하고 저장 건수를 반환한다."""
    if property_type not in TYPE_CONFIGS:
        raise ValueError(f"알 수 없는 부동산 유형: {property_type} (가능한 값: {list(TYPE_CONFIGS)})")
    config = TYPE_CONFIGS[property_type]

    settings = load_settings()
    if not settings.data_go_kr_api_key:
        raise MissingApiKeyError("공공데이터포털(DATA_GO_KR_API_KEY)")

    engine = engine or init_db()
    session = build_session()
    saved = 0

    for ymd in _month_range(start_ymd, end_ymd):
        xml_text = fetch_trades_page(config, region_code, ymd, settings.data_go_kr_api_key, session=session)
        trades = parse_trades_xml(xml_text, config, region_name=region_name)
        with get_session(engine) as db:
            for t in trades:
                existing = (
                    db.query(Trade)
                    .filter_by(
                        property_type=t["property_type"],
                        region_code=t["region_code"],
                        deal_date=t["deal_date"],
                        building_name=t["building_name"],
                        jibun=t["jibun"],
                        area_m2=t["area_m2"],
                        price_krw=t["price_krw"],
                    )
                    .first()
                )
                if existing:
                    continue
                db.add(Trade(**t))
                saved += 1
            db.commit()

    return saved
