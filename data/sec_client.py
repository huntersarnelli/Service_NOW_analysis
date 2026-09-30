"""
Polite SEC EDGAR requests: required User-Agent, at most 5 requests/second (SEC
limit is 10), and retries after timeouts / temporary server errors (429, 5xx).
Ported from the insider-trading repo (src/utils.py), where the SEC returned
intermittent 503s during long scans.
"""

from __future__ import annotations

import os
import time

import requests

# The SEC requires a contact name + email in every request. It comes from the SEC_USER_AGENT
# secret / environment variable (Streamlit exposes top-level secrets as environment variables;
# GitHub Actions passes it from the repo secrets) so no personal email lives in this public repo.
FALLBACK_USER_AGENT = "Deployment Desk (set SEC_USER_AGENT)"


def user_agent() -> str:
    """Read at request time, not import time: Streamlit only puts secrets into the
    environment once they are first loaded, which is after this module is imported."""
    return os.environ.get("SEC_USER_AGENT", "").strip() or FALLBACK_USER_AGENT
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
            response = requests.get(url, headers={"User-Agent": user_agent()}, timeout=timeout)
            if response.status_code not in RETRYABLE_STATUS or attempt == attempts:
                return response
        except (requests.Timeout, requests.ConnectionError):
            if attempt == attempts:
                raise
        time.sleep(10 * attempt)
    raise RuntimeError("unreachable")
