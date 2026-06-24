import re
from datetime import datetime

from sqlalchemy import select, func, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from models.news import Category, News

# 检索关键词清洗：常见疑问/填充词 + 过于宽泛的词，不作为有效检索项
_STOPWORDS = {
    "最近", "有什么", "什么", "请", "帮我", "给我", "一下", "这个", "那个",
    "新闻", "资讯", "文章", "报道", "条", "一条", "两条", "三条", "几条",
    "并", "标注", "来源", "我", "想", "看", "看看", "一些", "哪些", "怎么",
    "如何", "是", "在", "有", "和", "与", "的", "了", "吗", "呢", "关于", "最新",
}


def _extract_keywords(text: str, max_terms: int = 12) -> list[str]:
    """把用户输入（可能是整句）拆成可检索的词：英文词直接用，中文去停用词后取 2-gram。"""
    cleaned = re.sub(r"[^\w一-鿿]+", " ", text or "")
    terms: list[str] = []
    for token in cleaned.split():
        if token in _STOPWORDS:
            continue
        if token.isascii():
            if len(token) >= 2:
                terms.append(token.lower())
            continue
        # 中文：先按停用词切断，再对每段取 2-gram（无分词器时的折中召回）
        chunk = token
        for stop in _STOPWORDS:
            chunk = chunk.replace(stop, " ")
        for piece in chunk.split():
            if len(piece) < 2:
                continue
            if len(piece) <= 3:
                terms.append(piece)
            else:
                terms.extend(piece[i:i + 2] for i in range(len(piece) - 1))
    # 去重保序
    seen: list[str] = []
    for term in terms:
        if term not in seen:
            seen.append(term)
    return seen[:max_terms]


async def get_categories(db: AsyncSession, skip: int = 0, limit: int = 100):
    stmt = select(Category).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_news_list(db: AsyncSession, category_id: int, skip: int = 0, limit: int = 10):
    # 查询的是指定分类下的所有新闻
    stmt = select(News).where(News.category_id == category_id).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_news_count(db: AsyncSession, category_id: int):
    # 查询的是指定分类下的新闻数量
    stmt = select(func.count(News.id)).where(News.category_id == category_id)
    result = await db.execute(stmt)
    return result.scalar_one()  # 只能有一个结果，否则报错


async def get_news_detail(db: AsyncSession, news_id: int):
    stmt = select(News).where(News.id == news_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _relevance_score(news, terms: list[str], keyword: str, matched_cat_ids: set) -> int:
    """相关性打分：标题命中权重最高，整词短语命中额外加成；分类命中小幅加成。"""
    title = (news.title or "").lower()
    body = ((news.description or "") + " " + (news.content or "")).lower()
    score = 0
    for term in terms:
        t = term.lower()
        if t in title:
            score += 5      # 标题命中：强相关
        if t in body:
            score += 1      # 正文/简介命中：弱相关
    if keyword and keyword.lower() in title:
        score += 8          # 整句关键词原样出现在标题：最强信号（如"博鳌"）
    if matched_cat_ids and news.category_id in matched_cat_ids:
        score += 1
    return score


async def search_news(db: AsyncSession, keyword: str, limit: int = 5):
    keyword = (keyword or "").strip()
    safe_limit = min(max(limit, 1), 8)
    terms = _extract_keywords(keyword) if keyword else []

    # 无有效关键词：返回最新
    if not terms and not keyword:
        stmt = select(News).order_by(News.publish_time.desc(), News.views.desc()).limit(safe_limit)
        return (await db.execute(stmt)).scalars().all()

    conditions = []
    matched_cat_ids: set = set()
    if terms:
        for term in terms:
            pattern = f"%{term}%"
            conditions.extend([News.title.like(pattern), News.description.like(pattern), News.content.like(pattern)])
        categories = (await db.execute(select(Category))).scalars().all()
        matched_cat_ids = {
            cat.id for cat in categories for term in terms
            if cat.name and (cat.name in term or term in cat.name)
        }
        if matched_cat_ids:
            conditions.append(News.category_id.in_(matched_cat_ids))
    else:
        pattern = f"%{keyword}%"
        conditions = [News.title.like(pattern), News.description.like(pattern), News.content.like(pattern)]

    # 候选池：标题命中（强相关）单独保证入池，避免大表(上万行)下被截断挤掉 curated 文章；
    # 再补充正文/分类命中（按时间近的优先），合并后在内存里按相关性排序。
    title_conditions = [News.title.like(f"%{t}%") for t in terms] if terms else [News.title.like(f"%{keyword}%")]
    title_rows = (await db.execute(select(News).where(or_(*title_conditions)).limit(200))).scalars().all()
    broad_rows = (await db.execute(
        select(News).where(or_(*conditions)).order_by(News.publish_time.desc()).limit(400)
    )).scalars().all()
    merged = {n.id: n for n in title_rows}
    for n in broad_rows:
        merged.setdefault(n.id, n)
    candidates = list(merged.values())
    candidates.sort(
        key=lambda n: (_relevance_score(n, terms, keyword, matched_cat_ids),
                       n.publish_time or datetime.min),
        reverse=True,
    )
    return candidates[:safe_limit]


async def recommend_news(db: AsyncSession, limit: int = 5):
    """推荐候选（MVP 规则版）：按浏览量 + 发布时间排序的热门/最新新闻。"""
    safe_limit = min(max(limit, 1), 8)
    stmt = select(News).order_by(News.views.desc(), News.publish_time.desc()).limit(safe_limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def increase_news_views(db: AsyncSession, news_id: int):
    stmt = update(News).where(News.id == news_id).values(views=News.views + 1)
    result = await db.execute(stmt)
    await db.commit()

    # 更新 → 检查数据库是否真的命中了数据 → 命中了返回True
    return result.rowcount > 0


async def get_related_news(db: AsyncSession, news_id: int, category_id: int, limit: int = 5):
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
    # 列表推导式 推导出新闻的核心数据，然后再 return
    return [{
        "id": news_detail.id,
        "title": news_detail.title,
        "content": news_detail.content,
        "image": news_detail.image,
        "author": news_detail.author,
        "publishTime": news_detail.publish_time,
        "categoryId": news_detail.category_id,
        "views": news_detail.views
    } for news_detail in related_news]
