import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from crud import news_cache


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _Db:
    def __init__(self, rows):
        self.rows, self.statements = rows, []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self.rows)


class CategoryCacheTests(unittest.TestCase):
    rows = [{"id": i, "name": f"c{i}", "sort_order": i} for i in range(1, 10)]

    def test_first_paged_request_caches_the_full_list_not_its_page(self):
        cache = {}

        async def get_cached():
            return cache.get("categories")

        async def set_cached(value):
            cache["categories"] = value
            return True

        db = _Db(self.rows)
        with mock.patch.object(news_cache, "get_cached_categories", get_cached), \
                mock.patch.object(news_cache, "set_cache_categories", set_cached):
            first = asyncio.run(news_cache.get_categories(db, skip=0, limit=1))
            second = asyncio.run(news_cache.get_categories(db, skip=0, limit=100))
            third = asyncio.run(news_cache.get_categories(db, skip=7, limit=5))

        self.assertEqual([c["id"] for c in first], [1])
        self.assertEqual(len(second), 9)
        self.assertEqual([c["id"] for c in third], [8, 9])
        self.assertEqual(len(cache["categories"]), 9)
        self.assertEqual(len(db.statements), 1)  # served from cache after the first call
        self.assertIn("ORDER BY", str(db.statements[0]).upper())


if __name__ == "__main__":
    unittest.main()
