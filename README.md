# 부동산 자동산정모형(AVM)

공공데이터(국토교통부 실거래가, 브이월드 지오코더, 한국은행 기준금리)를 수집해
부동산 거래가격을 추정하는 모델을 학습/서빙하는 파이프라인입니다.

## 1. 설치

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

`.env`를 열어 아래 값을 채워주세요 (없어도 합성 샘플 데이터로 학습/예측은 바로 해볼 수 있습니다).

## 2. API 키 발급 방법

| 서비스 | 발급처 | 절차 |
|---|---|---|
| 국토교통부 실거래가(아파트) | [data.go.kr](https://www.data.go.kr) | 회원가입 → "국토교통부_아파트 매매 실거래가 자료" 검색 → 활용신청 → 마이페이지에서 인증키 확인 (보통 1~2시간, 드물게 최대 24시간). "상세 자료(Dev)"는 별도 API이니 혼동 주의 |
| 국토교통부 실거래가(연립다세대/단독다가구/오피스텔) | [data.go.kr](https://www.data.go.kr) | 아파트와 **별도로** 각각 활용신청 필요. "국토교통부 연립다세대 매매 실거래자료" / "단독다가구 매매 실거래자료" / "오피스텔 매매 실거래자료" 검색 |
| 건축물대장정보 서비스(건축HUB) | [data.go.kr](https://www.data.go.kr) | "건축물대장정보 서비스" 또는 "건축HUB" 검색 → 활용신청. 표제부/전유부 조회에 쓰임(웹 화면 자동조회 기능) |
| 브이월드 지오코더 | [vworld.kr](https://www.vworld.kr) | 회원가입 → 오픈API 인증키 신청 |
| 한국은행 ECOS | [ecos.bok.or.kr](https://ecos.bok.or.kr) | 회원가입 → OpenAPI 인증키 신청 |

한국은행 ECOS를 제외한 나머지(아파트/연립다세대/단독다가구/오피스텔 실거래가, 건축물대장, 브이월드)는 모두 실제 승인 키로 검증 완료했습니다. 건축물대장 응답은 다른 국토부 API(XML)와 달리 **JSON**으로 온다는 점 참고.

키는 `.env`의 `DATA_GO_KR_API_KEY`, `VWORLD_API_KEY`, `ECOS_API_KEY`에 넣습니다.

## 3. API 키 없이 바로 검증해보기 (합성 데이터)

```bash
python scripts/generate_sample_data.py   # DB를 초기화하고 합성 거래 600건 생성
python -m avm.cli features build
python -m avm.cli train
python -m avm.cli predict --input sample_input.json
```

`generate_sample_data.py`는 실제 지명이 아닌 가상 데이터를 만들며, 실행 시 DB(trades/geocache/rates)를 초기화합니다.

## 4. 실제 데이터 수집 (API 키 발급 후)

```bash
# 실거래가 수집: --type으로 부동산 유형 선택 (기본값 apt)
#   apt=아파트, rh=연립다세대, sh=단독/다가구, offi=오피스텔
# 지역코드는 법정동코드 앞 5자리 (예: 서울 종로구 11110)
# --region-name은 강력 권장 (아래 "주소 정확도" 참고)
python -m avm.cli collect trades --type apt --region 11110 --region-name "서울특별시 종로구" --start 202401 --end 202412

# 주소 -> 좌표 지오코딩
python -m avm.cli collect geocode

# 한국은행 기준금리
python -m avm.cli collect rates --start 202401 --end 202412

# 피처 생성 -> 학습 -> 예측
python -m avm.cli features build
python -m avm.cli train
python -m avm.cli predict --input sample_input.json
```

`collect trades`는 여러 월/유형에 걸쳐 실행해도 이미 저장된 거래는 건너뜁니다(자연키 기준 중복 방지).

**주소 정확도**: 실거래가 API의 `estateAgentSggNm`(공인중개사 사무소 소재지)은 매물 소재지와 다를 수 있어
(예: 종로구 매물을 서초구 소재 중개업소가 중개하는 경우) 주소 접두어로 쓰지 않습니다.
`--region-name`을 생략하면 동/지번만으로 주소가 구성되어 지오코딩 정확도가 떨어질 수 있으니 항상 넘겨주세요.

**참고**: `rh`(연립다세대)/`sh`(단독·다가구)/`offi`(오피스텔)는 data.go.kr에서 **아파트와 별도로 활용신청**해야 합니다.
필드 스키마(`avm/collectors/molit_generic.py`의 `TYPE_CONFIGS`)는 실제 승인된 키로 검증 완료했습니다.

## 5. 지도로 보기

```bash
python -m avm.cli map   # data/map.html 생성
```

지오코딩된 거래를 지도에 표시합니다. 마커 근처에 마우스를 올리면 상세정보가 뜨고, 지도를 움직이면 우측 패널에 현재 화면 안의 매물 목록이 갱신되며, 목록을 클릭하면 해당 마커로 이동합니다.

## 6. 가격산정 추계 웹 화면

```bash
uvicorn webapp.main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000` 접속 → 부동산 유형/위치(시도·법정동·지번, 선택적으로 건물동·호수)를 입력:

- **면적/건축년도를 입력하면**: 그 값 그대로 사용
- **비워두면**: VWorld로 좌표+지번코드(PNU)를 구해 건축물대장(표제부/전유부)을 자동조회해서 채움
  - 건물동/호수까지 입력하면 전유부에서 해당 호실의 전용면적/층을 정확히 찾음(집합건물)
  - 건물동/호수가 없으면 표제부의 건물 전체 연면적/지상층수를 참고치로 사용(단독/다가구 등)
  - 자동조회에 실패하면(API 미승인, 주소 못 찾음 등) 오류 안내와 함께 직접 입력을 요청함
  - 건물동/호수는 "104동"/"1301호"처럼 접미사를 붙여 입력해도, 붙이지 않아도(예: "104"/"1301") 됨

이후 공통으로: 학습된 모델(`models/avm_model.joblib`, 먼저 `avm.cli train`으로 생성해야 함)로 추정가를 계산하고, 반경 3km 이내 최근 실거래 비교 사례를 함께 표시합니다.

## 7. 예측 입력 형식 (`sample_input.json`, CLI `predict`용)

```json
{
  "area_m2": 84.93,
  "floor": 10,
  "age": 8,
  "lat": 37.5665,
  "lng": 126.978,
  "base_rate": 3.2,
  "deal_year": 2024,
  "deal_month": 6,
  "is_apt": 1,
  "is_rh": 0,
  "is_sh": 0,
  "is_offi": 0
}
```

`lat`/`lng`/`base_rate`는 없어도(null) 예측 가능하지만, 있을수록 정확도가 높아집니다. `is_*`는 부동산 유형 원-핫 인코딩(정확히 하나만 1).

## 8. 테스트

```bash
pytest
```

수집기(collectors)의 파싱 로직은 `tests/fixtures`의 API 응답 스키마 샘플로 검증하므로, API 키 없이도 전체 테스트가 통과합니다.

## 9. 다음 확장 아이디어

같은 수집기(collector) 패턴으로 아래 데이터를 추가할 수 있습니다:

- 표준지공시지가 / 개별공시지가 / 토지 실거래가
- 한국부동산원 R-ONE 통계(지수)
- 아파트/오피스텔 전월세 실거래가 (임대 수익률 계산용)
