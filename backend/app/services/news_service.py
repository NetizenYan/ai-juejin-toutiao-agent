from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.cache.news_cache import get_cached_categories, set_cache_categories, get_cache_news_list, set_cache_news_list, \
    get_cached_news_detail, cache_news_detail, get_cached_related_news, cache_related_news
from backend.app.models.news import Category, News
from backend.app.schemas.base import NewsItemBase
from backend.app.schemas.news import NewsDetailResponse, RelatedNewsResponse


async def get_categories(db: AsyncSession, skip: int = 0, limit: int = 100):
    # The cache holds the full ordered list under one key; paging is applied afterwards. Caching the
    # page itself under that key served the first caller's skip/limit to everyone for an hour.
    categories = await get_cached_categories()
    if not categories:
        stmt = select(Category).order_by(Category.sort_order, Category.id)
        result = await db.execute(stmt)
        categories = jsonable_encoder(result.scalars().all())
        if categories:
            await set_cache_categories(categories)
    return categories[skip:skip + limit]


async def get_news_list(db: AsyncSession, category_id: int, skip: int = 0, limit: int = 10):
    # 先尝试从缓存获取新闻列表
    # 跳过的数量skip = (页码 -1) * 每页数量 → 页码 = 跳过的数量 // 每页数量 + 1
    # await get_cache_news_list(分类id, 页码, 每页数量)
    page = skip // limit + 1
    cached_list = await get_cache_news_list(category_id, page, limit)  # 缓存数据 json
    if cached_list:
        return cached_list

    # 查询的是指定分类下的所有新闻，最新的在前；id 作为同一时刻的稳定次序，保证分页不重不漏
    stmt = (select(News).where(News.category_id == category_id)
            .order_by(News.publish_time.desc(), News.id.desc()).offset(skip).limit(limit))
    result = await db.execute(stmt)
    news_list = result.scalars().all()

    # 缓存命中与未命中返回同一结构：列表项不含正文 content，字段用前端约定的别名（publishTime/categoryId）
    news_data = [NewsItemBase.model_validate(item).model_dump(mode="json", by_alias=True) for item in news_list]
    if news_data:
        await set_cache_news_list(category_id, page, limit, news_data)

    return news_data


async def get_news_count(db: AsyncSession, category_id: int):
    # 查询的是指定分类下的新闻数量
    stmt = select(func.count(News.id)).where(News.category_id == category_id)
    result = await db.execute(stmt)
    return result.scalar_one()  # 只能有一个结果，否则报错


async def get_news_detail(db: AsyncSession, news_id: int):
    # 先尝试从缓存获取
    cached_news = await get_cached_news_detail(news_id)
    if cached_news:
        # 缓存数据可能包含 related_news，需要过滤掉（News 模型没有这个字段）
        # filtered_data = {k: v for k, v in cached_news.items() if k != 'related_news'}
        # return News(**filtered_data)
        return News(**cached_news)

    stmt = select(News).where(News.id == news_id)
    result = await db.execute(stmt)
    news = result.scalar_one_or_none()

    # 如果查询到数据，存入缓存（不使用别名，保持数据库字段名）
    if news:
        # 构造新闻详情数据用于缓存（包含 content 字段）
        # news_dict = {k: v for k, v in news.__dict__.items() if not k.startswith('_')}
        news_dict = NewsDetailResponse.model_validate(news).model_dump(
            by_alias=False, mode="json", exclude={'related_news'}
        )
        await cache_news_detail(news_id, news_dict)

    return news


async def increase_news_views(db: AsyncSession, news_id: int):
    stmt = update(News).where(News.id == news_id).values(views=News.views + 1)
    result = await db.execute(stmt)
    await db.commit()

    # 更新 → 检查数据库是否真的命中了数据 → 命中了返回True
    return result.rowcount > 0


async def get_related_news(db: AsyncSession, news_id: int, category_id: int, limit: int = 5):
    cached_related = await get_cached_related_news(news_id, category_id)
    if cached_related:
        # 缓存数据是字典列表，直接返回
        return cached_related
    # order_by 排序 → 浏览量和发布时间
    stmt = select(News).where(
        News.category_id == category_id,
        News.id != news_id
    ).order_by(
        News.views.desc(),  # 默认是升序，desc 表示降序
        News.publish_time.desc()
    ).limit(limit)
    result = await db.execute(stmt)
    # return result.scalars().all()
    related_news = result.scalars().all()

    # 转换为字典格式用于缓存和返回（不使用别名，保持数据库字段名）
    if related_news:
        related_data = [
            RelatedNewsResponse.model_validate(news).model_dump(by_alias=False, mode="json")
            for news in related_news
        ]
        await cache_related_news(news_id, category_id, related_data)
        return related_data

    # 没有相关新闻，返回空列表
    return []
    # 列表推导式 推导出新闻的核心数据，然后再 return
    # return [{
    #     "id": news_detail.id,
    #     "title": news_detail.title,
    #     "content": news_detail.content,
    #     "image": news_detail.image,
    #     "author": news_detail.author,
    #     "publishTime": news_detail.publish_time,
    #     "categoryId": news_detail.category_id,
    #     "views": news_detail.views
    # } for news_detail in related_news]
