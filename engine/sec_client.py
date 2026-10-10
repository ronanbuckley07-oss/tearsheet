"""HTTP client for SEC EDGAR.

Three jobs, all required by the SEC's fair-access policy or by CLAUDE.md:

1. Identify ourselves. Every request carries a User-Agent with a name and a
   contact email (read from .env). The SEC blocks anonymous traffic.
2. Stay under 10 requests per second. A process-wide limiter spaces requests
   at least ``min_interval`` seconds apart (default 0.11s, about 9/s).
3. Cache every response on disk, so repeat runs don't re-download. Each cached
   body is stored next to a small metadata file recording the URL and when it
   was fetched, so any figure can later say how fresh its source data was.

This module knows nothing about finance. It returns parsed JSON, or raw text
for the few non-JSON documents we read (a filing's XBRL instance).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from engine import config

SEC_MAX_REQUESTS_PER_SECOND = 10
DEFAULT_MIN_INTERVAL = 0.11  # seconds between requests -> ~9 req/s, under the SEC cap
DEFAULT_MAX_AGE = 24 * 60 * 60  # cached responses older than a day are refetched
RETRY_STATUSES = {429, 500, 502, 503, 504}


class SECError(RuntimeError):
    """A request to EDGAR failed or returned something unusable."""


class SECConfigError(SECError):
    """The client is missing required configuration (name/email)."""


class RateLimiter:
    """Enforces a minimum gap between calls. Thread-safe."""

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if min_interval < 1 / SEC_MAX_REQUESTS_PER_SECOND:
            raise ValueError(
                f"min_interval {min_interval}s would exceed "
                f"{SEC_MAX_REQUESTS_PER_SECOND} requests/second"
            )
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last is not None:
                remaining = self.min_interval - (now - self._last)
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._clock()
            self._last = now


@dataclass(frozen=True)
class CachedResponse:
    url: str
    fetched_at: str  # ISO 8601 UTC
    from_cache: bool
    data: Any


def build_user_agent(name: str | None, email: str | None) -> str:
    if not name or not email or "@" not in email:
        raise SECConfigError(
            "SEC requests need a name and a real contact email. Set SEC_USER_NAME and "
            "SEC_CONTACT_EMAIL in .env (see .env.example), or in the app's Secrets on "
            "Streamlit Community Cloud."
        )
    return f"{name.strip()} {email.strip()}"


class SECClient:
    def __init__(
        self,
        user_agent: str | None = None,
        cache_dir: Path | str | None = None,
        max_age: float | None = DEFAULT_MAX_AGE,
        rate_limiter: RateLimiter | None = None,
        session: requests.Session | None = None,
        max_retries: int = 3,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if user_agent is None:
            user_agent = build_user_agent(config.sec_user_name(), config.sec_contact_email())
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir) if cache_dir else config.CACHE_DIR
        self.max_age = max_age
        self.rate_limiter = rate_limiter or _shared_limiter()
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.timeout = timeout
        self._sleep = sleep

    # ---- public -------------------------------------------------------------

    def get_json(self, url: str, refresh: bool = False) -> Any:
        """Return parsed JSON for ``url``, from disk cache when fresh."""
        return self.fetch(url, refresh=refresh).data

    def get_text(self, url: str, refresh: bool = False) -> str:
        """Return the body of ``url`` as text (for XML documents), cached like JSON."""
        return self.fetch(url, refresh=refresh, as_text=True).data

    def fetch(self, url: str, refresh: bool = False, as_text: bool = False) -> CachedResponse:
        body_path, meta_path = self._cache_paths(url)
        if not refresh:
            cached = self._read_cache(url, body_path, meta_path)
            if cached is not None:
                return cached

        data = self._download(url, as_text=as_text)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._write_cache(body_path, meta_path, url, fetched_at, data)
        return CachedResponse(url=url, fetched_at=fetched_at, from_cache=False, data=data)

    # ---- network ------------------------------------------------------------

    def _download(self, url: str, as_text: bool = False) -> Any:
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        last_error: str = ""
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.wait()
            try:
                resp = self.session.get(url, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    if as_text:
                        return resp.text
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise SECError(f"{url} did not return JSON") from exc
                if resp.status_code not in RETRY_STATUSES:
                    raise SECError(f"{url} returned HTTP {resp.status_code}")
                last_error = f"HTTP {resp.status_code}"
            if attempt < self.max_retries:
                self._sleep(2**attempt)  # 1s, 2s, 4s
        raise SECError(f"{url} failed after {self.max_retries + 1} attempts ({last_error})")

    # ---- disk cache ---------------------------------------------------------

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        parsed = urlparse(url)
        stem = Path(parsed.path).name or "index"
        digest = hashlib.sha256(url.encode()).hexdigest()[:12]
        base = self.cache_dir / parsed.netloc / f"{Path(stem).stem}-{digest}"
        return base.with_suffix(".json"), base.with_suffix(".meta.json")

    def _read_cache(self, url: str, body_path: Path, meta_path: Path) -> CachedResponse | None:
        if not body_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text())
            if self.max_age is not None:
                fetched = datetime.fromisoformat(meta["fetched_at"])
                age = (datetime.now(timezone.utc) - fetched).total_seconds()
                if age > self.max_age:
                    return None
            data = json.loads(body_path.read_text())
        except (OSError, ValueError, KeyError):
            return None  # corrupt cache entry: refetch
        return CachedResponse(url=url, fetched_at=meta["fetched_at"], from_cache=True, data=data)

    def _write_cache(
        self, body_path: Path, meta_path: Path, url: str, fetched_at: str, data: Any
    ) -> None:
        body_path.parent.mkdir(parents=True, exist_ok=True)
        # Write to temp files then rename, so an interrupted run never leaves
        # a half-written body that a later run would trust.
        # The temp names are per thread: report.load_companies fetches in parallel.
        tag = f"{threading.get_ident()}.tmp"
        tmp_body = body_path.with_suffix(f".json.{tag}")
        tmp_body.write_text(json.dumps(data))
        tmp_body.replace(body_path)
        tmp_meta = meta_path.with_suffix(f".{tag}")
        tmp_meta.write_text(json.dumps({"url": url, "fetched_at": fetched_at}))
        tmp_meta.replace(meta_path)


_limiter_lock = threading.Lock()
_limiter: RateLimiter | None = None


def _shared_limiter() -> RateLimiter:
    """One limiter per process, so several clients can't jointly exceed the cap."""
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = RateLimiter()
        return _limiter
