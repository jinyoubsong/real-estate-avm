import json
import re

import pytest
import responses

from avm.collectors.base import MissingApiKeyError
from avm.collectors.ecos_rates import collect_rates, parse_ecos_response
from avm.db import BaseRate, get_session
from conftest import read_fixture

ECOS_URL_RE = re.compile(r"https://ecos\.bok\.or\.kr/api/StatisticSearch/.*")


def test_parse_ecos_response_ok():
    data = json.loads(read_fixture("ecos_rates_sample.json"))
    rows = parse_ecos_response(data)
    assert rows == [
        {"month": "2024-01", "base_rate": 3.5},
        {"month": "2024-02", "base_rate": 3.5},
    ]


def test_parse_ecos_response_error():
    with pytest.raises(RuntimeError):
        parse_ecos_response({"RESULT": {"CODE": "ERROR-100", "MESSAGE": "인증키 오류"}})


@responses.activate
def test_collect_rates_saves_rows(db_engine, monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "dummy-key")
    responses.add(responses.GET, ECOS_URL_RE, json=json.loads(read_fixture("ecos_rates_sample.json")), status=200)

    saved = collect_rates(start="202401", end="202402", engine=db_engine)

    assert saved == 2
    with get_session(db_engine) as db:
        assert db.query(BaseRate).count() == 2
        row = db.get(BaseRate, "2024-01")
        assert row.base_rate == 3.5


def test_collect_rates_requires_api_key(db_engine, monkeypatch):
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        collect_rates(start="202401", end="202402", engine=db_engine)
