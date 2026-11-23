"""Unit tests for mcp_server/fx_logic.py  (no network, no MCP SDK needed)."""
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))
import fx_logic  # noqa: E402

SAMPLE = {"result": "success", "time_last_update_utc": "Tue, 17 Nov 2026 00:00:01 +0000",
          "rates": {"USD": 1, "EGP": 48.0, "EUR": 0.9}}


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ExchangeRateTests(unittest.TestCase):
    def make(self, fetcher=None, ttl=3600):
        self.calls = []

        def default(base):
            self.calls.append(base)
            return SAMPLE

        self.clock = FakeClock()
        return fx_logic.ExchangeRateService(fetcher or default, ttl=ttl, clock=self.clock)

    def test_conversion(self):
        out = self.make().get_rate("usd", "egp", 100)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["pair"], "USD/EGP")
        self.assertEqual(out["converted_amount"], 4800.0)
        self.assertIn("ليس سعر بنك CIB", out["disclaimer_ar"])
        self.assertEqual(out["last_update_utc"], SAMPLE["time_last_update_utc"])

    def test_cache_and_expiry(self):
        svc = self.make(ttl=100)
        svc.get_rate("USD", "EGP")
        svc.get_rate("USD", "EUR")
        self.assertEqual(self.calls, ["USD"])  # second call served from cache
        self.clock.now = 101
        svc.get_rate("USD", "EGP")
        self.assertEqual(self.calls, ["USD", "USD"])  # expired, fetched again

    def test_validation(self):
        svc = self.make()
        for args in [("XXX", "EGP", 1), ("USD", "USD", 1), ("USD", "EGP", 0), ("USD", "EGP", -5),
                     ("USD", "EGP", "abc"), ("USD", "EGP", float("inf")), ("USD", "EGP", 10**12)]:
            self.assertEqual(svc.get_rate(*args)["status"], "error", args)
        self.assertEqual(self.calls, [])  # nothing was fetched for invalid input

    def test_service_failure_is_reported_not_raised(self):
        def boom(base):
            raise urllib.error.URLError("down")

        out = self.make(fetcher=boom).get_rate("USD", "EGP")
        self.assertEqual(out["status"], "error")
        self.assertNotIn("down", out["message"])  # internal details are not leaked

    def test_missing_target_rate(self):
        out = self.make(fetcher=lambda b: {"result": "success", "rates": {"USD": 1}}).get_rate("USD", "EGP")
        self.assertEqual(out["status"], "error")


if __name__ == "__main__":
    unittest.main()
