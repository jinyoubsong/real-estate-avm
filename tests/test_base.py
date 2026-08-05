from avm.collectors.base import sanitize_error


def test_sanitize_error_masks_service_key():
    exc = Exception("403 Client Error: Forbidden for url: https://apis.data.go.kr/x?serviceKey=SUPERSECRET123&LAWD_CD=11110")
    assert "SUPERSECRET123" not in sanitize_error(exc)
    assert "key=***" in sanitize_error(exc)


def test_sanitize_error_masks_vworld_key():
    exc = Exception("Connection error for https://api.vworld.kr/req/address?key=ABCDEF-1234&address=foo")
    assert "ABCDEF-1234" not in sanitize_error(exc)
    assert "key=***" in sanitize_error(exc)


def test_sanitize_error_passes_through_plain_messages():
    exc = Exception("아무 키도 없는 평범한 오류 메시지")
    assert sanitize_error(exc) == "아무 키도 없는 평범한 오류 메시지"
