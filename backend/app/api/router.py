"""All API routes of the news site, mounted by backend.app.main."""
from fastapi import APIRouter

from backend.app.api.routes import ai, favorite, history, news, users

api_router = APIRouter()
api_router.include_router(news.router)
api_router.include_router(users.router)
api_router.include_router(favorite.router)
api_router.include_router(history.router)
api_router.include_router(ai.router)
