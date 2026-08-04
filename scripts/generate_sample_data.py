"""API 키 없이 파이프라인(features/train/predict)을 검증하기 위한 합성 샘플 데이터 생성기.

주의: 이 스크립트는 DB의 trades/geocache/rates 테이블을 초기화(drop&create)하고
합성 데이터로 채운다. 실제 수집 데이터를 보존해야 한다면 실행하지 말 것.
"""

import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from avm.db import Base, BaseRate, GeoCache, Trade, get_engine, get_session  # noqa: E402

random.seed(42)

# 서울 시내 5개 가상 동 (실제 지명이 아닌 데모용)
NEIGHBORHOODS = [
    {"name": "가상동1", "base_lat": 37.5665, "base_lng": 126.9780, "price_level": 1.3},
    {"name": "가상동2", "base_lat": 37.5219, "base_lng": 127.0411, "price_level": 1.1},
    {"name": "가상동3", "base_lat": 37.4979, "base_lng": 127.0276, "price_level": 1.5},
    {"name": "가상동4", "base_lat": 37.5486, "base_lng": 127.0700, "price_level": 1.0},
    {"name": "가상동5", "base_lat": 37.6392, "base_lng": 127.0254, "price_level": 0.8},
]

N_TRADES = 600
PRICE_PER_M2_BASE = 15_000_000  # 원/m^2 기준 단가 (데모용 임의값)


def month_range(start: date, end: date) -> list[str]:
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def main() -> None:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    months = month_range(date(2023, 1, 1), date(2024, 12, 1))

    with get_session(engine) as db:
        # 기준금리: 완만히 하락하는 가상 시계열
        for i, month in enumerate(months):
            rate = round(3.5 - i * 0.03 + random.uniform(-0.05, 0.05), 2)
            db.add(BaseRate(month=month, base_rate=max(rate, 1.5)))

        # 동네별 좌표 캐시
        addresses = {}
        for n in NEIGHBORHOODS:
            for jibun_no in range(1, 41):
                address = f"{n['name']} {jibun_no}"
                lat = n["base_lat"] + random.uniform(-0.01, 0.01)
                lng = n["base_lng"] + random.uniform(-0.01, 0.01)
                db.add(GeoCache(address=address, lat=lat, lng=lng))
                addresses[address] = (n, lat, lng)
        address_list = list(addresses.items())

        # 합성 거래 데이터
        for _ in range(N_TRADES):
            address, (neighborhood, lat, lng) = random.choice(address_list)
            month_idx = random.randrange(len(months))
            year, month = map(int, months[month_idx].split("-"))
            day = random.randint(1, 27)
            area = round(random.uniform(39, 135), 2)
            floor = random.randint(1, 25)
            build_year = random.randint(1988, 2023)
            age = year - build_year

            price_per_m2 = (
                PRICE_PER_M2_BASE
                * neighborhood["price_level"]
                * (1 + 0.01 * min(floor, 20))
                * max(0.6, 1 - age * 0.01)
            )
            noise = random.uniform(0.92, 1.08)
            price = int(price_per_m2 * area * noise)

            db.add(
                Trade(
                    property_type="apt",
                    region_code="00000",
                    deal_date=date(year, month, day),
                    building_name=f"{neighborhood['name']}아파트",
                    jibun=address.split(" ")[-1],
                    area_m2=area,
                    floor=floor,
                    build_year=build_year,
                    price_krw=price,
                    address=address,
                )
            )

        db.commit()

    print(f"합성 데이터 생성 완료: trades={N_TRADES}, geocache={len(addresses)}, rates={len(months)}")


if __name__ == "__main__":
    main()
