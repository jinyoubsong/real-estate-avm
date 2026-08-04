from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .config import load_settings


class Base(DeclarativeBase):
    pass


PROPERTY_TYPES = ("apt", "rh", "sh", "offi")
PROPERTY_TYPE_LABELS = {
    "apt": "아파트",
    "rh": "연립다세대",
    "sh": "단독/다가구",
    "offi": "오피스텔",
}


class Trade(Base):
    """국토교통부 실거래가 원자료 한 건 (여러 부동산 유형 공용)."""

    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint(
            "property_type", "region_code", "deal_date", "building_name", "jibun", "area_m2", "price_krw",
            name="uq_trade_natural_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    property_type: Mapped[str] = mapped_column(String(10), default="apt")
    region_code: Mapped[str] = mapped_column(String(10))
    deal_date: Mapped[date] = mapped_column(Date)
    building_name: Mapped[str] = mapped_column(String(200))
    jibun: Mapped[str] = mapped_column(String(100))
    area_m2: Mapped[float] = mapped_column(Float)
    floor: Mapped[int] = mapped_column(Integer)
    build_year: Mapped[int] = mapped_column(Integer)
    price_krw: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class GeoCache(Base):
    """주소 -> 위경도 캐시 (VWorld 지오코더 호출 결과)."""

    __tablename__ = "geocache"

    address: Mapped[str] = mapped_column(String(300), primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class BaseRate(Base):
    """한국은행 기준금리 시계열 (월 단위)."""

    __tablename__ = "rates"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # "YYYY-MM"
    base_rate: Mapped[float] = mapped_column(Float)


def get_engine(db_path=None):
    settings = load_settings()
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}")


def init_db(engine=None):
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session(engine=None) -> Session:
    engine = engine or init_db()
    return Session(engine)
