"""Polite HTTP client: per-host rate limiting, retry with backoff, request budget."""

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class RequestBudgetExceeded(RuntimeError):
    pass


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        min_interval: float = 2.0,
        max_requests: int = 20,
        max_retries: int = 3,
        timeout: float = 20.0,
        sleep=time.sleep,
    ):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.min_interval = min_interval
        self.max_requests = max_requests
        self.max_retries = max_retries
        self.timeout = timeout
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._blocked_until: dict[str, float] = {}
        self.requests_made = 0

    def _wait_for_slot(self, host: str) -> None:
        now = time.monotonic()
        last = self._last_request.get(host)
        wait = self.min_interval - (now - last) if last is not None else 0
        wait = max(wait, self._blocked_until.get(host, 0) - now)
        if wait > 0:
            self._sleep(wait)
        self._last_request[host] = time.monotonic()

    def _note_rate_limit(self, host: str, resp: requests.Response) -> float | None:
        """Honor X-Ratelimit-* headers (used by Reddit). Returns seconds until reset if exhausted."""
        remaining, reset = resp.headers.get("x-ratelimit-remaining"), resp.headers.get("x-ratelimit-reset")
        try:
            if remaining is not None and reset is not None and float(remaining) < 1:
                delay = min(float(reset) + 1, 120)
                self._blocked_until[host] = time.monotonic() + delay
                return delay
        except ValueError:
            pass
        return None

    def get(self, url: str) -> requests.Response:
        host = urlparse(url).netloc
        for attempt in range(self.max_retries + 1):
            if self.requests_made >= self.max_requests:
                raise RequestBudgetExceeded(f"request budget of {self.max_requests} used up")
            self._wait_for_slot(host)
            self.requests_made += 1
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    raise
                backoff = 2 ** attempt * 5
                log.warning("network error on %s (%s); retrying in %ss", host, type(exc).__name__, backoff)
                self._sleep(backoff)
                continue
            reset_in = self._note_rate_limit(host, resp)
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    backoff = int(retry_after)
                else:
                    backoff = reset_in or 2 ** attempt * 10
                backoff = min(backoff, 60)
                log.warning("HTTP %s from %s; retrying in %.0fs", resp.status_code, host, backoff)
                self._sleep(backoff)
                continue
            return resp
        raise RuntimeError("unreachable")
