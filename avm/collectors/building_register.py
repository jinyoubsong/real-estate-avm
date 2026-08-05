"""건축물대장(건축HUB) 표제부/전유부 조회 — 주소 기반 스펙 자동조회.

VWorld 지오코딩 응답의 구조화 필드(`level4LC`, PNU 유사 코드)를 파싱해
건축물대장 API 호출에 필요한 시군구코드/법정동코드/지번을 얻는다.

응답은 JSON이다(실제 승인 키로 확인 완료). 표제부(getBrTitleInfo)는 집합건물의 경우
동(棟)별로 한 행씩 오고, 전유부(getBrExposPubuseAreaInfo)는 exposPubuseGbCd로
전유("1")/공용("2") 면적이 섞여 온다 — 전용면적을 구하려면 "1"만 걸러야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import load_settings
from .base import MissingApiKeyError, build_session, sanitize_error
from .vworld_geocode import geocode_address_detailed

TITLE_ENDPOINT = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
EXPOS_ENDPOINT = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo"

EXPOS_GB_EXCLUSIVE = "1"  # 전유


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


def _check_header(data: dict) -> None:
    header = data.get("header", {})
    code = header.get("resultCode")
    if code not in (None, "00", "000"):
        raise RuntimeError(f"건축물대장 API 오류 [{code}]: {header.get('resultMsg', '알 수 없는 오류')}")


def _items(data: dict) -> list[dict]:
    """body.items.item은 결과가 0건이면 빈 문자열, 1건이면 dict, 여러 건이면 list로 온다."""
    items_obj = data.get("body", {}).get("items")
    if not isinstance(items_obj, dict):
        return []
    item = items_obj.get("item")
    if item is None or item == "":
        return []
    return item if isinstance(item, list) else [item]


def parse_title_json(data: dict) -> list[dict]:
    """표제부: 집합건물은 동(棟)별로 한 행. 연면적/대지면적/사용승인일/주용도/지상층수."""
    _check_header(data)
    return [
        {
            "dong_name": item.get("dongNm") or "",
            "total_floor_area": float(item.get("totArea") or 0),
            "plat_area": float(item.get("platArea") or 0),
            "approval_date": item.get("useAprDay") or "",
            "main_purpose": item.get("mainPurpsCdNm") or "",
            "ground_floors": int(item.get("grndFlrCnt") or 0),
        }
        for item in _items(data)
    ]


def parse_expos_json(data: dict) -> list[dict]:
    """전유부: 동/호, 전유면적, 층. exposPubuseGbCd(1=전유/2=공용)를 함께 반환한다."""
    _check_header(data)
    return [
        {
            "dong_name": item.get("dongNm") or "",
            "ho_name": item.get("hoNm") or "",
            "exclusive_area": float(item.get("area") or 0),
            "floor": int(item.get("flrNo") or 0),
            "floor_name": item.get("flrNoNm") or "",
            "expos_gb": item.get("exposPubuseGbCd") or "",
        }
        for item in _items(data)
    ]


def fetch_title_info(pnu: Pnu, api_key: str, session=None) -> list[dict]:
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
            "numOfRows": 30,
            "pageNo": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return parse_title_json(resp.json())


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
            "numOfRows": 100,
            "pageNo": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return parse_expos_json(resp.json())


def _normalize_unit_token(value: str) -> str:
    """'104동' -> '104', '1301호' -> '1301'. API 값과 사용자 입력의 접미사 표기 차이를 흡수한다."""
    return value.strip().rstrip("동호")


def _approval_year(approval_date: str) -> int:
    """'20090630' 형식 문자열에서 연도를 뽑는다."""
    return int(approval_date[:4]) if len(approval_date) >= 4 and approval_date[:4].isdigit() else 0


def lookup_building_spec(address: str, dong_name: str = "", ho_name: str = "") -> dict:
    """주소(+선택적 건물동/호)로 면적/층/건축년도를 자동 조회한다.

    반환: {"area_m2", "floor", "build_year", "lat", "lng", "warning"}
    일부만 조회 가능하면 나머지는 None으로 채우고 warning에 이유를 남긴다.
    (동/호가 없으면 표제부의 건물(동) 연면적/지상층수를 참고치로 사용한다 —
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

    norm_dong = _normalize_unit_token(dong_name) if dong_name else ""
    norm_ho = _normalize_unit_token(ho_name) if ho_name else ""

    try:
        titles = fetch_title_info(pnu, settings.data_go_kr_api_key)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 원인을 보여주되 API 키는 가림
        result["warning"] = f"건축물대장 조회 실패: {sanitize_error(exc)}"
        return result

    title = None
    if titles:
        if norm_dong:
            title = next((t for t in titles if _normalize_unit_token(t["dong_name"]) == norm_dong), None)
        title = title or titles[0]
        result["build_year"] = _approval_year(title["approval_date"]) or None

    if norm_dong or norm_ho:
        try:
            units = fetch_expos_info(pnu, settings.data_go_kr_api_key)
        except Exception:  # noqa: BLE001
            units = []
        match = next(
            (
                u
                for u in units
                if u["expos_gb"] == EXPOS_GB_EXCLUSIVE
                and (not norm_dong or _normalize_unit_token(u["dong_name"]) == norm_dong)
                and (not norm_ho or _normalize_unit_token(u["ho_name"]) == norm_ho)
            ),
            None,
        )
        if match:
            result["area_m2"] = match["exclusive_area"] or None
            result["floor"] = match["floor"] or None
        else:
            result["warning"] = "동/호에 해당하는 전유부 정보를 찾지 못해 면적/층은 직접 입력해 주세요."
    elif title:
        result["area_m2"] = title["total_floor_area"] or None
        result["floor"] = title["ground_floors"] or None

    return result
