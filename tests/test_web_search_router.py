"""Failover policy of the multi-backend web search router."""
import asyncio
import os
import tempfile
import unittest

from harness.web_search_router import (
    ERROR_COOLDOWN_SECONDS,
    SearchBlocked,
    WebSearchRouter,
)


class _Clock:
    def __init__(self):
        self.now = 1_000_000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _items(*urls):
    return [{"title": url, "url": url, "summary": "s"} for url in urls]


class _Backend:
    """Plays back a list of behaviours: a list of items, an exception, or [] for an empty answer."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    async def __call__(self, client, query, limit):
        self.calls += 1
        step = self.script.pop(0) if self.script else []
        if isinstance(step, Exception):
            raise step
        return step


def _router(clock, backends, order=None, **kwargs):
    options = dict(block_cooldown=600, block_cooldown_max=2400, min_interval=0, cache_ttl=0, clock=clock, sleep=clock.sleep)
    options.update(kwargs)
    return WebSearchRouter(backends, order or list(backends), **options)


def _search(router, query="q", limit=5):
    return asyncio.run(router.search(None, query, limit))


class FailoverTests(unittest.TestCase):
    def test_first_backend_with_results_wins(self):
        clock = _Clock()
        baidu, searx = _Backend(_items("https://a.cn/1")), _Backend(_items("https://b.cn/1"))

        outcome = _search(_router(clock, {"baidu": baidu, "searx": searx}))

        self.assertEqual(outcome.backend, "baidu")
        self.assertEqual(searx.calls, 0)

    def test_a_block_falls_through_and_cools_the_backend_down(self):
        clock = _Clock()
        baidu = _Backend(SearchBlocked("verification page"), _items("https://a.cn/1"))
        searx = _Backend(_items("https://b.cn/1"), _items("https://b.cn/2"))
        router = _router(clock, {"baidu": baidu, "searx": searx})

        first = _search(router)
        self.assertEqual(first.backend, "searx")
        self.assertEqual([a.outcome for a in first.attempts], ["blocked", "ok"])

        clock.now += 599
        second = _search(router)
        self.assertEqual(second.attempts[0].outcome, "cooling")
        self.assertEqual(baidu.calls, 1)

        clock.now += 2
        self.assertEqual(_search(router).backend, "baidu")

    def test_repeated_blocks_double_the_cooldown_up_to_the_cap(self):
        clock = _Clock()
        baidu = _Backend(*[SearchBlocked("captcha")] * 4)
        router = _router(clock, {"baidu": baidu, "searx": _Backend(*[_items("https://b.cn/1")] * 4)})

        waits = []
        for _ in range(4):
            _search(router)
            state = router._load()["baidu"]
            waits.append(state.blocked_until - clock.now)
            clock.now = state.blocked_until

        self.assertEqual(waits, [600, 1200, 2400, 2400])

    def test_an_error_message_that_reads_like_a_block_counts_as_a_block(self):
        clock = _Clock()
        router = _router(clock, {"baidu": _Backend(RuntimeError("HTTP 403 Forbidden")), "searx": _Backend(_items("https://b.cn/1"))})

        self.assertEqual(_search(router).attempts[0].outcome, "blocked")

    def test_repeated_errors_pause_a_dead_backend_briefly(self):
        clock = _Clock()
        router = _router(clock, {"baidu": _Backend(*[ConnectionError("refused")] * 3), "searx": _Backend(*[_items("https://b.cn/1")] * 3)})

        for _ in range(3):
            _search(router)

        self.assertEqual(router._load()["baidu"].blocked_until - clock.now, ERROR_COOLDOWN_SECONDS)

    def test_repeated_empty_answers_are_treated_as_a_silent_block(self):
        clock = _Clock()
        router = _router(clock, {"baidu": _Backend(*[[]] * 6), "searx": _Backend(*[_items("https://b.cn/1")] * 6)})

        for _ in range(2):
            _search(router)
        self.assertEqual(router._load()["baidu"].blocked_until, 0)
        _search(router)
        self.assertEqual(router._load()["baidu"].blocked_until - clock.now, 600)

        clock.now = router._load()["baidu"].blocked_until
        for _ in range(3):
            _search(router)
        self.assertEqual(router._load()["baidu"].blocked_until - clock.now, 1200)

    def test_a_success_resets_the_streaks(self):
        clock = _Clock()
        router = _router(clock, {"baidu": _Backend([], [], _items("https://a.cn/1"), [], [])})

        for _ in range(5):
            _search(router)

        self.assertEqual(router._load()["baidu"].blocked_until, 0)

    def test_nothing_found_is_not_a_failure_but_every_backend_down_is(self):
        clock = _Clock()
        empty = _search(_router(clock, {"baidu": _Backend([]), "searx": _Backend([])}))
        down = _search(_router(clock, {"baidu": _Backend(SearchBlocked("captcha")), "searx": _Backend(ConnectionError())}))

        partly = _search(_router(clock, {"baidu": _Backend(SearchBlocked("captcha")), "searx": _Backend([])}))

        self.assertFalse(empty.failed or empty.incomplete)
        self.assertTrue(down.failed)
        self.assertFalse(partly.failed)
        self.assertTrue(partly.incomplete)


class PacingTests(unittest.TestCase):
    def test_a_backend_called_too_soon_is_skipped_for_the_next_one(self):
        clock = _Clock()
        baidu = _Backend(_items("https://a.cn/1"), _items("https://a.cn/2"))
        searx = _Backend(_items("https://b.cn/1"))
        router = _router(clock, {"baidu": baidu, "searx": searx}, min_interval=3)

        _search(router, "q1")
        clock.now += 1
        second = _search(router, "q2")

        self.assertEqual(second.backend, "searx")
        self.assertEqual(second.attempts[0].outcome, "throttled")
        self.assertEqual(clock.slept, [])

    def test_waits_for_a_throttled_backend_only_when_the_others_fail(self):
        clock = _Clock()
        baidu = _Backend(_items("https://a.cn/1"), _items("https://a.cn/2"))
        router = _router(clock, {"baidu": baidu, "searx": _Backend(SearchBlocked("captcha"))}, min_interval=3)

        _search(router, "q1")
        clock.now += 1
        second = _search(router, "q2")

        self.assertEqual(second.backend, "baidu")
        self.assertEqual(clock.slept, [2])

    def test_a_repeated_query_is_served_from_the_cache_until_it_expires(self):
        clock = _Clock()
        baidu = _Backend(_items("https://a.cn/1"), _items("https://a.cn/2"))
        router = _router(clock, {"baidu": baidu}, cache_ttl=60)

        _search(router, "神舟三号  推迟")
        cached = _search(router, "神舟三号 推迟")
        clock.now += 61
        _search(router, "神舟三号 推迟")

        self.assertTrue(cached.cached)
        self.assertEqual(baidu.calls, 2)


class StateAndFilterTests(unittest.TestCase):
    def test_cooldowns_survive_a_new_router_through_the_state_file(self):
        clock = _Clock()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            _search(_router(clock, {"baidu": _Backend(SearchBlocked("captcha")), "searx": _Backend(_items("https://b.cn/1"))}, state_path=path))
            baidu = _Backend(_items("https://a.cn/1"))

            outcome = _search(_router(clock, {"baidu": baidu, "searx": _Backend(_items("https://b.cn/1"))}, state_path=path))

        self.assertEqual(outcome.attempts[0].outcome, "cooling")
        self.assertEqual(baidu.calls, 0)

    def test_results_are_filtered_deduplicated_and_limited(self):
        clock = _Clock()
        raw = _items("https://a.cn/1", "https://a.cn/1", "https://spam.example/2", "", "https://a.cn/3", "https://a.cn/4")
        router = _router(clock, {"baidu": _Backend(raw)}, keep_item=lambda item: "spam" not in item["url"])

        outcome = _search(router, limit=2)

        self.assertEqual([it["url"] for it in outcome.items], ["https://a.cn/1", "https://a.cn/3"])

    def test_results_all_filtered_away_count_as_empty(self):
        clock = _Clock()
        router = _router(clock, {"baidu": _Backend(_items("https://spam.example/1")), "searx": _Backend(_items("https://b.cn/1"))},
                         keep_item=lambda item: "spam" not in item["url"])

        outcome = _search(router)

        self.assertEqual([a.outcome for a in outcome.attempts], ["empty", "ok"])


if __name__ == "__main__":
    unittest.main()
