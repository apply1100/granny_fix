import json
import unittest
from unittest.mock import patch

from services import bitmex_watcher_service, coinalyze_service, okx_btc_alert_service


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class ProxyBypassTests(unittest.TestCase):
    def test_coinalyze_request_uses_direct_opener(self) -> None:
        with patch.object(
            coinalyze_service._DIRECT_HTTP_OPENER,
            "open",
            return_value=_FakeResponse([]),
        ) as mocked_open:
            result = coinalyze_service._request_json("secret", "/future-markets", {})

        self.assertEqual(result, [])
        mocked_open.assert_called_once()

    def test_bitmex_request_uses_direct_opener(self) -> None:
        payload = [
            {
                "trdMatchID": "abc",
                "timestamp": "2026-04-09T00:00:00Z",
                "side": "Buy",
                "size": 1000000,
                "price": 70000,
                "symbol": "XBTUSD",
            }
        ]
        with patch.object(
            bitmex_watcher_service._DIRECT_HTTP_OPENER,
            "open",
            return_value=_FakeResponse(payload),
        ) as mocked_open:
            result = bitmex_watcher_service._fetch_recent_trades()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].trade_id, "abc")
        mocked_open.assert_called_once()

    def test_okx_btc_request_uses_direct_opener(self) -> None:
        payload = {"series": [{"id": "test", "points": []}]}
        with patch.dict("os.environ", {"KIYOTAKA_API_KEY": "test-key"}, clear=False):
            with patch.object(
                okx_btc_alert_service._DIRECT_HTTP_OPENER,
                "open",
                return_value=_FakeResponse(payload),
            ) as mocked_open:
                result = okx_btc_alert_service._request_json("https://example.com", {"hello": "world"})

        self.assertEqual(result, payload)
        mocked_open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
