"""국토교통부 아파트매매 실거래가 수집기 — `molit_generic`의 apt 설정 래퍼.

기존 CLI/테스트가 기대하는 아파트 전용 함수 시그니처(지역코드/기간만 받음)를
유지하기 위한 얇은 래퍼다. 실제 파싱/수집 로직은 `molit_generic`에 있다.
"""

from __future__ import annotations

from . import molit_generic

ENDPOINT = molit_generic.TYPE_CONFIGS["apt"].endpoint


def parse_trades_xml(xml_text: str, region_name: str = "") -> list[dict]:
    return molit_generic.parse_trades_xml(xml_text, molit_generic.TYPE_CONFIGS["apt"], region_name=region_name)


def fetch_trades_page(
    region_code: str,
    deal_ymd: str,
    api_key: str,
    page_no: int = 1,
    num_of_rows: int = 1000,
    session=None,
) -> str:
    return molit_generic.fetch_trades_page(
        molit_generic.TYPE_CONFIGS["apt"],
        region_code,
        deal_ymd,
        api_key,
        page_no=page_no,
        num_of_rows=num_of_rows,
        session=session,
    )


def collect_trades(
    region_code: str,
    start_ymd: str,
    end_ymd: str,
    region_name: str = "",
    engine=None,
) -> int:
    return molit_generic.collect_trades(
        "apt", region_code, start_ymd, end_ymd, region_name=region_name, engine=engine
    )
