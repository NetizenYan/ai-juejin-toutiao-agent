from typing import Any

from config.cache_conf import get_json_cache, set_cache


CATEGORIES_KEY = "news:categories"
CATEGORY_TTL_SECONDS = 3600
LIST_TTL_SECONDS = 1800
DETAIL_TTL_SECONDS = 3600
RELATED_TTL_SECONDS = 1800


def _news_list_key(category_id: int, page: int, page_size: int) -> str:
    return f"news:list:{category_id}:{page}:{page_size}"


def _news_detail_key(news_id: int) -> str:
    return f"news:detail:{news_id}"


def _related_news_key(news_id: int, category_id: int) -> str:
    return f"news:related:{news_id}:{category_id}"


async def get_cached_categories() -> Any | None:
    return await get_json_cache(CATEGORIES_KEY)


async def set_cache_categories(categories: list[dict[str, Any]]) -> bool:
    return await set_cache(CATEGORIES_KEY, categories, expire=CATEGORY_TTL_SECONDS)


async def get_cache_news_list(category_id: int, page: int, page_size: int) -> Any | None:
    return await get_json_cache(_news_list_key(category_id, page, page_size))


async def set_cache_news_list(category_id: int, page: int, page_size: int, news_list: list[dict[str, Any]]) -> bool:
    return await set_cache(_news_list_key(category_id, page, page_size), news_list, expire=LIST_TTL_SECONDS)


async def get_cached_news_detail(news_id: int) -> Any | None:
    return await get_json_cache(_news_detail_key(news_id))


async def cache_news_detail(news_id: int, detail: dict[str, Any]) -> bool:
    return await set_cache(_news_detail_key(news_id), detail, expire=DETAIL_TTL_SECONDS)


async def get_cached_related_news(news_id: int, category_id: int) -> Any | None:
    return await get_json_cache(_related_news_key(news_id, category_id))


async def cache_related_news(news_id: int, category_id: int, related_news: list[dict[str, Any]]) -> bool:
    return await set_cache(_related_news_key(news_id, category_id), related_news, expire=RELATED_TTL_SECONDS)
