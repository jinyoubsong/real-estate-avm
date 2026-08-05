"""건축물대장(건축HUB) 표제부/전유부 조회 — 주소 기반 스펙 자동조회.

VWorld 지오코딩 응답의 구조화 필드(`level4LC`, PNU 유사 코드)를 파싱해
건축물대장 API 호출에 필요한 시군구코드/법정동코드/지번을 얻는다.

주의: 건축물대장 API는 실거래가 API와 별도 활용신청이 필요하며, 아래 필드명은
공개 문서 기반 최선 추정치다 — 실제 승인된 키로 확인 전까지는 미검증.
필드가 없으면 예외 대신 빈 값/0으로 처리된다(파서가 관대함, `_text` 참고).
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

from ..config import load_settings
from .base import MissingApiKeyError, build_session, sanitize_error
from .vworld_geocode import geocode_address_detailed

TITLE_ENDPOINT = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
EXPOS_ENDPOINT = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo"


@dataclass(frozen=True)
class Pnu:
    sigungu_cd: str
    bjdong_cd: str
    plat_gb_cd: str
    bun: str
    ji: str


def parse_pnu(code: str) -> Pnu:
    """VWorld structure.level4LC(19자리)를 시군구코드/법정동코드/지번으로 분해한다.

    형식: 법정동코드(10) + 산여부(1, '1'=일반/'2'=산) + 본번(4) + 부번(4)
    """
    if len(code) < 19:
        raise ValueError(f"PNU 코드 길이가 올바르지 않습니다: {code!r}")
    sigungu_cd = code[0:5]
    bjdong_cd = code[5:10]
    mountain_flag = code[10]
    plat_gb_cd = "0" if mountain_flag == "1" else "1"
    bun = code[11:15]
    ji = code[15:19]
    return Pnu(sigungu_cd, bjdong_cd, plat_gb_cd, bun, ji)


def _text(item: ElementTree.Element, tag: str, default: str = "") -> str:
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else default


def _check_header(root: ElementTree.Element) -> None:
    header_code = root.findtext("./header/resultCode")
    if header_code not in (None, "00", "000"):
        msg = root.findtext("./header/resultMsg", default="알 수 없는 오류")
        raise RuntimeError(f"건축물대장 API 오류 [{header_code}]: {msg}")


def parse_title_xml(xml_text: str) -> dict | None:
    """표제부(건물 총괄 정보): 연면적, 대지면적, 사용승인일, 주용도, 지상층수."""
    root = ElementTree.fromstring(xml_text)
    _check_header(root)
    item = root.find("./body/items/item")
    if item is None:
        return None
    return {
        "total_floor_area": float(_text(item, "totArea", "0") or 0),
        "plat_area": float(_text(item, "platArea", "0") or 0),
        "approval_date": _text(item, "useAprDay"),
        "main_purpose": _text(item, "mainPurpsCdNm"),
        "ground_floors": int(_text(item, "grndFlrCnt", "0") or 0),
    }


def parse_expos_xml(xml_text: str) -> list[dict]:
    """전유부(집합건물 호실별 정보): 동/호, 전유면적, 층."""
    root = ElementTree.fromstring(xml_text)
    _check_header(root)
    return [
        {
            "dong_name": _text(item, "dongNm"),
            "ho_name": _text(item, "hoNm"),
            "exclusive_area": float(_text(item, "area", "0") or 0),
            "floor_name": _text(item, "flrNoNm"),
        }
        for item in root.findall("./body/items/item")
    ]


def fetch_title_info(pnu: Pnu, api_key: str, session=None) -> dict | None:
    session = session or build_session()
    resp = session.get(
        TITLE_ENDPOINT,
        params={
            "serviceKey": api_key,
            "sigunguCd": pnu.sigungu_cd,
            "bjdongCd": pnu.bjdong_cd,
            "platGbCd": pnu.plat_gb_cd,
            "bun": pnu.bun,
            "ji": pnu.ji,
            "numOfRows": 10,
            "pageNo": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return parse_title_xml(resp.text)


def fetch_expos_info(pnu: Pnu, api_key: str, session=None) -> list[dict]:
    session = session or build_session()
    resp = session.get(
        EXPOS_ENDPOINT,
        params={
            "serviceKey": api_key,
            "sigunguCd": pnu.sigungu_cd,
            "bjdongCd": pnu.bjdong_cd,
            "platGbCd": pnu.plat_gb_cd,
            "bun": pnu.bun,
            "ji": pnu.ji,
            "numOfRows": 50,
            "pageNo": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return parse_expos_xml(resp.text)


def _floor_number(floor_name: str) -> int:
    """'제3층' 같은 문자열에서 정수 층수를 뽑는다. 지하는 음수로 처리."""
    digits = "".join(ch for ch in floor_name if ch.isdigit())
    if not digits:
        return 0
    value = int(digits)
    return -value if "지하" in floor_name else value


def _approval_year(approval_date: str) -> int:
    """'20090630' 형식 문자열에서 연도를 뽑는다."""
    return int(approval_date[:4]) if len(approval_date) >= 4 and approval_date[:4].isdigit() else 0


def lookup_building_spec(address: str, dong_name: str = "", ho_name: str = "") -> dict:
    """주소(+선택적 건물동/호)로 면적/층/건축년도를 자동 조회한다.

    반환: {"area_m2", "floor", "build_year", "lat", "lng", "warning"}
    일부만 조회 가능하면 나머지는 None으로 채우고 warning에 이유를 남긴다.
    (동/호가 없으면 표제부의 건물 전체 연면적/지상층수를 참고치로 사용한다 —
    단독/다가구처럼 호실 구분이 없는 유형에 적합하고, 집합건물은 부정확할 수 있다.)
    """
    settings = load_settings()
    if not settings.vworld_api_key:
        raise MissingApiKeyError("브이월드(VWORLD_API_KEY)")
    if not settings.data_go_kr_api_key:
        raise MissingApiKeyError("공공데이터포털(DATA_GO_KR_API_KEY)")

    result = {"area_m2": None, "floor": None, "build_year": None, "lat": None, "lng": None, "warning": None}

    geo = geocode_address_detailed(address, settings.vworld_api_key)
    if geo is None:
        result["warning"] = "주소 좌표/코드를 찾지 못했습니다."
        return result

    result["lat"] = geo["lat"]
    result["lng"] = geo["lng"]

    if not geo.get("pnu"):
        result["warning"] = "지번 코드를 확인하지 못해 건축물대장을 조회할 수 없습니다."
        return result

    try:
        pnu = parse_pnu(geo["pnu"])
    except ValueError:
        result["warning"] = "지번 코드 형식을 해석하지 못했습니다."
        return result

    try:
        title = fetch_title_info(pnu, settings.data_go_kr_api_key)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 원인을 보여주되 API 키는 가림
        result["warning"] = f"건축물대장 조회 실패: {sanitize_error(exc)}"
        return result

    if title:
        result["build_year"] = _approval_year(title["approval_date"]) or None

    if dong_name or ho_name:
        try:
            units = fetch_expos_info(pnu, settings.data_go_kr_api_key)
        except Exception:  # noqa: BLE001
            units = []
        match = next(
            (
                u
                for u in units
                if (not dong_name or u["dong_name"] == dong_name) and (not ho_name or u["ho_name"] == ho_name)
            ),
            None,
        )
        if match:
            result["area_m2"] = match["exclusive_area"] or None
            result["floor"] = _floor_number(match["floor_name"]) or None
        else:
            result["warning"] = "동/호에 해당하는 전유부 정보를 찾지 못해 면적/층은 직접 입력해 주세요."
    elif title:
        result["area_m2"] = title["total_floor_area"] or None
        result["floor"] = title["ground_floors"] or None

    return result
