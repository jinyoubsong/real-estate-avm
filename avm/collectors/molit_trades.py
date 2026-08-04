"""국토교통부 아파트매매 실거래가 수집기 (data.go.kr RTMSDataSvcAptTrade).

API 문서: https://www.data.go.kr/data/15057511/openapi.do
(주의: 같은 데이터의 "상세" 버전(RTMSDataSvcAptTradeDev)은 별도 활용신청/승인이
필요하며 스키마도 다르다. 이 모듈은 기본 버전(RTMSDataSvcAptTrade) 기준.)
"""

from __future__ import annotations

from datetime import date
from xml.etree import ElementTree

from ..config import load_settings
from ..db import Trade, get_session, init_db
from .base import MissingApiKeyError, build_session

ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"


def _text(item: ElementTree.Element, tag: str, default: str = "") -> str:
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else default


def parse_trades_xml(xml_text: str, region_name: str = "") -> list[dict]:
    """RTMSDataSvcAptTrade 응답 XML을 dict 리스트로 변환한다.

    거래금액(dealAmount)은 API 응답 단위(만원)를 원 단위로 환산해 저장한다.
    시군구명(estateAgentSggNm)은 API 응답에 포함되어 있어 기본 주소 접두어로
    쓰되, region_name을 명시하면 그 값으로 덮어쓴다.
    """
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
                "region_code": _text(item, "sggCd"),
                "deal_date": date(year, month, day),
                "apt_name": _text(item, "aptNm"),
                "jibun": jibun,
                "area_m2": float(_text(item, "excluUseAr", "0")),
                "floor": int(_text(item, "floor", "0") or 0),
                "build_year": int(_text(item, "buildYear", "0") or 0),
                "price_krw": int(price_manwon) * 10_000,
                "address": address,
            }
        )
    return trades


def fetch_trades_page(
    region_code: str,
    deal_ymd: str,
    api_key: str,
    page_no: int = 1,
    num_of_rows: int = 1000,
    session=None,
) -> str:
    session = session or build_session()
    resp = session.get(
        ENDPOINT,
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


def collect_trades(
    region_code: str,
    start_ymd: str,
    end_ymd: str,
    region_name: str = "",
    engine=None,
) -> int:
    """지정 기간의 아파트매매 실거래가를 수집해 DB에 저장하고 저장 건수를 반환한다."""
    settings = load_settings()
    if not settings.data_go_kr_api_key:
        raise MissingApiKeyError("공공데이터포털(DATA_GO_KR_API_KEY)")

    engine = engine or init_db()
    session = build_session()
    saved = 0

    for ymd in _month_range(start_ymd, end_ymd):
        xml_text = fetch_trades_page(region_code, ymd, settings.data_go_kr_api_key, session=session)
        trades = parse_trades_xml(xml_text, region_name=region_name)
        with get_session(engine) as db:
            for t in trades:
                existing = (
                    db.query(Trade)
                    .filter_by(
                        region_code=t["region_code"],
                        deal_date=t["deal_date"],
                        apt_name=t["apt_name"],
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
