"""
Polite SEC EDGAR requests: required User-Agent, at most 5 requests/second (SEC
limit is 10), and retries after timeouts / temporary server errors (429, 5xx).
Ported from the insider-trading repo (src/utils.py), where the SEC returned
intermittent 503s during long scans.
"""

from __future__ import annotations

import time

import requests

SEC_USER_AGENT = "Hunter Sarnelli huntersarnelli1@gmail.com"
SECONDS_BETWEEN_REQUESTS = 0.2
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_last_request = 0.0


def _wait() -> None:
    global _last_request
    gap = time.time() - _last_request
    if gap < SECONDS_BETWEEN_REQUESTS:
        time.sleep(SECONDS_BETWEEN_REQUESTS - gap)
    _last_request = time.time()


def sec_get(url: str, attempts: int = 4, timeout: int = 30) -> requests.Response:
    """GET from sec.gov with rate limiting and retries (waits 10s, 20s, 30s...)."""
    for attempt in range(1, attempts + 1):
        _wait()
        try:
            response = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=timeout)
            if response.status_code not in RETRYABLE_STATUS or attempt == attempts:
                return response
        except (requests.Timeout, requests.ConnectionError):
            if attempt == attempts:
                raise
        time.sleep(10 * attempt)
    raise RuntimeError("unreachable")
