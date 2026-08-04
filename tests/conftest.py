from pathlib import Path

import pytest

from avm.db import init_db, get_engine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def db_engine(tmp_path):
    engine = get_engine(db_path=tmp_path / "test.db")
    init_db(engine)
    return engine
