import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_API_KEY_PARAM_RE = re.compile(r"(?:serviceKey|key)=[^&\s]+")


def sanitize_error(exc: Exception) -> str:
    """예외 메시지에 URL 쿼리로 섞여 나올 수 있는 API 키를 가려서 반환한다."""
    return _API_KEY_PARAM_RE.sub("key=***", str(exc))


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


class MissingApiKeyError(RuntimeError):
    def __init__(self, name: str):
        super().__init__(
            f"{name} API 키가 설정되지 않았습니다. .env에 값을 채워주세요 (.env.example 참고)."
        )
