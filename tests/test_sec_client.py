import json
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests

from engine.sec_client import (
    RateLimiter,
    SECClient,
    SECConfigError,
    SECError,
    build_user_agent,
)

URL = "https://data.sec.gov/submissions/CIK0000320193.json"
UA = "Test User test@example.com"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False, text=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Stands in for requests.Session; records calls, replays queued responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class NoWaitLimiter(RateLimiter):
    def __init__(self):
        super().__init__()
        self.waits = 0

    def wait(self):
        self.waits += 1


def make_client(tmp_path, responses, **kw):
    session = FakeSession(responses)
    client = SECClient(
        user_agent=UA,
        cache_dir=tmp_path,
        rate_limiter=kw.pop("rate_limiter", NoWaitLimiter()),
        session=session,
        sleep=lambda s: None,
        **kw,
    )
    return client, session


# ---- User-Agent ---------------------------------------------------------------


def test_user_agent_header_sent(tmp_path):
    client, session = make_client(tmp_path, [FakeResponse(payload={"a": 1})])
    client.get_json(URL)
    assert session.calls[0]["headers"]["User-Agent"] == UA


@pytest.mark.parametrize("name,email", [(None, "a@b.com"), ("Name", None), ("Name", "no-at")])
def test_user_agent_requires_name_and_email(name, email):
    with pytest.raises(SECConfigError):
        build_user_agent(name, email)


def test_user_agent_format():
    assert build_user_agent(" Jane Doe ", "jane@x.com ") == "Jane Doe jane@x.com"


# ---- disk cache ---------------------------------------------------------------


def test_second_call_served_from_disk(tmp_path):
    client, session = make_client(tmp_path, [FakeResponse(payload={"a": 1})])
    first = client.fetch(URL)
    second = client.fetch(URL)
    assert len(session.calls) == 1
    assert first.from_cache is False and second.from_cache is True
    assert second.data == {"a": 1}
    assert second.fetched_at == first.fetched_at


def test_cache_survives_new_client(tmp_path):
    client, _ = make_client(tmp_path, [FakeResponse(payload={"a": 1})])
    client.get_json(URL)
    client2, session2 = make_client(tmp_path, [])
    assert client2.get_json(URL) == {"a": 1}
    assert session2.calls == []


def test_refresh_bypasses_cache(tmp_path):
    client, session = make_client(
        tmp_path, [FakeResponse(payload={"v": 1}), FakeResponse(payload={"v": 2})]
    )
    client.get_json(URL)
    assert client.get_json(URL, refresh=True) == {"v": 2}
    assert client.get_json(URL) == {"v": 2}
    assert len(session.calls) == 2


def test_stale_cache_refetched(tmp_path):
    client, session = make_client(
        tmp_path, [FakeResponse(payload={"v": 1}), FakeResponse(payload={"v": 2})], max_age=60
    )
    client.get_json(URL)
    _, meta_path = client._cache_paths(URL)
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    meta_path.write_text(json.dumps({"url": URL, "fetched_at": old}))
    assert client.get_json(URL) == {"v": 2}


def test_max_age_none_never_expires(tmp_path):
    client, session = make_client(tmp_path, [FakeResponse(payload={"v": 1})], max_age=None)
    client.get_json(URL)
    _, meta_path = client._cache_paths(URL)
    meta_path.write_text(json.dumps({"url": URL, "fetched_at": "2000-01-01T00:00:00+00:00"}))
    assert client.get_json(URL) == {"v": 1}
    assert len(session.calls) == 1


def test_corrupt_cache_refetched(tmp_path):
    client, session = make_client(
        tmp_path, [FakeResponse(payload={"v": 1}), FakeResponse(payload={"v": 2})]
    )
    client.get_json(URL)
    body_path, _ = client._cache_paths(URL)
    body_path.write_text("{truncated")
    assert client.get_json(URL) == {"v": 2}


def test_distinct_urls_distinct_cache_files(tmp_path):
    client, _ = make_client(tmp_path, [])
    a = client._cache_paths("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json")
    b = client._cache_paths("https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json")
    assert a[0] != b[0]


def test_failed_request_not_cached(tmp_path):
    client, _ = make_client(tmp_path, [FakeResponse(status_code=404)])
    with pytest.raises(SECError):
        client.get_json(URL)
    body_path, meta_path = client._cache_paths(URL)
    assert not body_path.exists() and not meta_path.exists()


# ---- errors and retries -------------------------------------------------------


def test_404_raises_without_retry(tmp_path):
    client, session = make_client(tmp_path, [FakeResponse(status_code=404)])
    with pytest.raises(SECError, match="404"):
        client.get_json(URL)
    assert len(session.calls) == 1


def test_non_json_raises(tmp_path):
    client, _ = make_client(tmp_path, [FakeResponse(bad_json=True)])
    with pytest.raises(SECError, match="JSON"):
        client.get_json(URL)


def test_retries_on_429_then_succeeds(tmp_path):
    client, session = make_client(
        tmp_path, [FakeResponse(status_code=429), FakeResponse(payload={"ok": True})]
    )
    assert client.get_json(URL) == {"ok": True}
    assert len(session.calls) == 2


def test_retries_on_connection_error(tmp_path):
    client, session = make_client(
        tmp_path, [requests.ConnectionError("boom"), FakeResponse(payload={"ok": True})]
    )
    assert client.get_json(URL) == {"ok": True}


def test_gives_up_after_max_retries(tmp_path):
    client, session = make_client(tmp_path, [FakeResponse(status_code=503)] * 3, max_retries=2)
    with pytest.raises(SECError, match="3 attempts"):
        client.get_json(URL)
    assert len(session.calls) == 3


def test_every_attempt_goes_through_rate_limiter(tmp_path):
    limiter = NoWaitLimiter()
    client, _ = make_client(
        tmp_path,
        [FakeResponse(status_code=429), FakeResponse(payload={})],
        rate_limiter=limiter,
    )
    client.get_json(URL)
    assert limiter.waits == 2


def test_cache_hit_skips_rate_limiter(tmp_path):
    limiter = NoWaitLimiter()
    client, _ = make_client(tmp_path, [FakeResponse(payload={})], rate_limiter=limiter)
    client.get_json(URL)
    client.get_json(URL)
    assert limiter.waits == 1


# ---- rate limiter -------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_rate_limiter_spaces_calls():
    clock = FakeClock()
    rl = RateLimiter(min_interval=0.11, clock=clock, sleep=clock.sleep)
    times = []
    for _ in range(20):
        rl.wait()
        times.append(clock.t)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g >= 0.11 - 1e-9 for g in gaps)
    # 20 requests can't fit in under 19 * 0.11s, i.e. never 10+ in any second
    assert times[-1] - times[0] >= 19 * 0.11 - 1e-9


def test_rate_limiter_no_sleep_when_already_spaced():
    clock = FakeClock()
    rl = RateLimiter(min_interval=0.11, clock=clock, sleep=clock.sleep)
    rl.wait()
    clock.t += 1.0
    rl.wait()
    assert clock.slept == []


def test_rate_limiter_rejects_interval_over_sec_cap():
    with pytest.raises(ValueError):
        RateLimiter(min_interval=0.05)


def test_get_text_returns_body_and_caches(tmp_path):
    xml_url = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x-20260630_htm.xml"
    client, session = make_client(tmp_path, [FakeResponse(text="<xbrl/>")])
    assert client.get_text(xml_url) == "<xbrl/>"
    assert client.get_text(xml_url) == "<xbrl/>"
    assert len(session.calls) == 1


# ---- live (opt-in) ------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API")
def test_live_fetch_apple_submissions(tmp_path):
    client = SECClient(cache_dir=tmp_path)  # reads name/email from .env
    data = client.get_json(URL)
    assert data["cik"].lstrip("0") == "320193"
    assert client.fetch(URL).from_cache is True
