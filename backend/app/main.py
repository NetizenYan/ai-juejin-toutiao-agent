"""The news site's API: news, users, favourites, history, and the chat endpoint that hands over to the agent."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.harness.mcp_pool import close_all as close_mcp_sessions
from backend.app.api.router import api_router
from backend.app.core.config import cors_allow_credentials, cors_allowed_origins
from backend.app.core.exception_handlers import register_exception_handlers


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await close_mcp_sessions()  # stop the resident MCP server subprocesses


app = FastAPI(lifespan=lifespan)

# 注册异常处理器
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],     # 允许的请求方法
    allow_headers=["*"],     # 允许的请求头
)


@app.get("/")
async def root():
    return {"message": "Hello World"}


# 挂载路由/注册路由
app.include_router(api_router)
