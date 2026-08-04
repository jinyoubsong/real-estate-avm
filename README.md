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
| 국토교통부 실거래가 | [data.go.kr](https://www.data.go.kr) | 회원가입 → "국토교통부_아파트 매매 실거래가 자료" 검색 → 활용신청 → 마이페이지에서 인증키 확인 (보통 1~2시간, 드물게 최대 24시간). "상세 자료(Dev)"는 별도 API이니 혼동 주의 |
| 브이월드 지오코더 | [vworld.kr](https://www.vworld.kr) | 회원가입 → 오픈API 인증키 신청 |
| 한국은행 ECOS | [ecos.bok.or.kr](https://ecos.bok.or.kr) | 회원가입 → OpenAPI 인증키 신청 |

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
# 아파트매매 실거래가 (지역코드는 법정동코드 앞 5자리, 예: 서울 종로구 11110)
# --region-name은 선택사항 (생략하면 API 응답의 시군구명을 자동 사용)
python -m avm.cli collect trades --region 11110 --start 202401 --end 202412

# 주소 -> 좌표 지오코딩
python -m avm.cli collect geocode

# 한국은행 기준금리
python -m avm.cli collect rates --start 202401 --end 202412

# 피처 생성 -> 학습 -> 예측
python -m avm.cli features build
python -m avm.cli train
python -m avm.cli predict --input sample_input.json
```

`collect trades`는 여러 월에 걸쳐 실행해도 이미 저장된 거래는 건너뜁니다(자연키 기준 중복 방지).

## 5. 예측 입력 형식 (`sample_input.json`)

```json
{
  "area_m2": 84.93,
  "floor": 10,
  "age": 8,
  "lat": 37.5665,
  "lng": 126.978,
  "base_rate": 3.2,
  "deal_year": 2024,
  "deal_month": 6
}
```

`lat`/`lng`/`base_rate`는 없어도(null) 예측 가능하지만, 있을수록 정확도가 높아집니다.

## 6. 테스트

```bash
pytest
```

수집기(collectors)의 파싱 로직은 `tests/fixtures`의 실제 API 응답 스키마 샘플로 검증하므로, API 키 없이도 전체 테스트가 통과합니다.

## 7. 다음 확장 아이디어

같은 수집기(collector) 패턴으로 아래 데이터를 추가할 수 있습니다:

- 표준지공시지가 / 개별공시지가
- 건축물대장(건축HUB)
- 한국부동산원 R-ONE 통계(지수)
- 아파트 전월세 실거래가 (임대 수익률 계산용)
