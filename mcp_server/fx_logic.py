"""
fx_logic.py
===========
Pure logic of the exchange-rate tool. Standard library only, so it is easy to test
without the MCP SDK and without network access (the HTTP fetcher is injectable).

The rate is an INDICATIVE market reference rate from a free public API.
It is NOT a CIB rate, and the tool output says so explicitly.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from typing import Callable

# Currencies the tool accepts (a short allow-list keeps the tool predictable).
ALLOWED_CURRENCIES = {"EGP", "USD", "EUR", "GBP", "SAR", "AED", "KWD", "QAR", "CHF", "JPY", "CAD"}

API_URL = "https://open.er-api.com/v6/latest/{base}"  # free endpoint, no API key, updated daily
CACHE_TTL_SECONDS = 3600  # the source updates once a day, so one hour of caching is safe
MAX_AMOUNT = 1_000_000_000
HTTP_TIMEOUT_SECONDS = 8.0

SOURCE = "ExchangeRate-API open access (open.er-api.com)"
ATTRIBUTION = "Rates By Exchange Rate API (https://www.exchangerate-api.com)"
DISCLAIMER_AR = (
    "سعر استرشادي يتحدّث مرة يوميًا من مصدر خارجي، وهو ليس سعر بنك CIB. "
    "السعر الفعلي للتحويل يُعرف من الفرع أو الاتصال بـ 19666."
)

Fetcher = Callable[[str], dict]


def fetch_rates_http(base: str) -> dict:
    """Download the latest rates for ``base`` and return the decoded JSON."""
    request = urllib.request.Request(
        API_URL.format(base=base), headers={"User-Agent": "cib-tools-mcp/1.0 (educational project)"}
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310 (fixed https URL)
        data = json.loads(response.read().decode("utf-8"))
    if data.get("result") != "success":
        raise ValueError("rate service did not return success")
    return data


def _error(message: str) -> dict:
    return {"status": "error", "message": message}


class ExchangeRateService:
    """Validate the request, fetch (with a small cache) and convert."""

    def __init__(self, fetcher: Fetcher = fetch_rates_http, ttl: int = CACHE_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._fetcher = fetcher
        self._ttl = ttl
        self._clock = clock
        self._cache: dict[str, tuple[float, dict]] = {}

    def _rates_for(self, base: str) -> dict:
        cached = self._cache.get(base)
        now = self._clock()
        if cached and now - cached[0] < self._ttl:
            return cached[1]
        data = self._fetcher(base)
        self._cache[base] = (now, data)
        return data

    def get_rate(self, from_currency: str, to_currency: str, amount: float = 1.0) -> dict:
        src = str(from_currency).strip().upper()
        dst = str(to_currency).strip().upper()
        if src not in ALLOWED_CURRENCIES or dst not in ALLOWED_CURRENCIES:
            return _error(f"unsupported currency. Supported: {', '.join(sorted(ALLOWED_CURRENCIES))}")
        if src == dst:
            return _error("from_currency and to_currency must be different")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return _error("amount must be a number")
        if not math.isfinite(amount) or amount <= 0 or amount > MAX_AMOUNT:
            return _error(f"amount must be greater than 0 and at most {MAX_AMOUNT}")

        try:
            data = self._rates_for(src)
            rates = data.get("rates") or data.get("conversion_rates") or {}
            rate = float(rates[dst])
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, KeyError):
            return _error("exchange-rate service is currently unavailable")

        return {
            "status": "ok",
            "pair": f"{src}/{dst}",
            "rate": round(rate, 6),
            "amount": amount,
            "converted_amount": round(amount * rate, 4),
            "last_update_utc": data.get("time_last_update_utc"),
            "source": SOURCE,
            "attribution": ATTRIBUTION,
            "disclaimer_ar": DISCLAIMER_AR,
        }
