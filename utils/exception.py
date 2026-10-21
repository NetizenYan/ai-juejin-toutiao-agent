import logging
import os
import traceback

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette import status

logger = logging.getLogger(__name__)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# 详细错误只允许通过本地开发环境变量显式开启。
DEBUG_MODE = _bool_env("APP_DEBUG_ERRORS", False)


async def http_exception_handler(request: Request, exc: HTTPException):
    """
    处理 HTTPException 异常
    """
    # HTTPException 通常是业务逻辑主动抛出的，data 保持 None
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail,
            "data": None
        }
    )


# 唯一约束名 → 提示文案（约束名见 models/*.py 与 sql/mysql_schema.sql）
_UNIQUE_CONSTRAINT_MESSAGES = (
    ("username_UNIQUE", "用户名已存在"),
    ("phone_UNIQUE", "手机号已被使用"),
    ("user_news_unique", "已经收藏过这条新闻"),
    ("token_UNIQUE", "令牌冲突，请重新登录"),
)


def integrity_error_detail(error_msg: str) -> str:
    """把数据库完整性错误映射为用户可读的提示，按具体约束区分，而不是一律提示用户名已存在。"""
    for constraint, message in _UNIQUE_CONSTRAINT_MESSAGES:
        if constraint in error_msg:
            return message
    if "Duplicate entry" in error_msg or "UNIQUE constraint failed" in error_msg:
        return "数据已存在，请勿重复提交"
    if "FOREIGN KEY" in error_msg or "foreign key constraint" in error_msg.lower():
        return "关联数据不存在"
    return "数据约束冲突，请检查输入"


async def integrity_error_handler(request: Request, exc: IntegrityError):
    """
    处理数据库完整性约束错误
    """
    error_msg = str(exc.orig)
    detail = integrity_error_detail(error_msg)

    # 开发模式下返回详细错误信息
    error_data = None
    if DEBUG_MODE:
        error_data = {
            "error_type": "IntegrityError",
            "error_detail": error_msg,
            "path": str(request.url)
        }

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": 400,
            "message": detail,
            "data": error_data
        }
    )


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    """
    处理 SQLAlchemy 数据库错误
    """
    logger.error(
        "SQLAlchemy error while handling %s",
        request.url,
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    # 开发模式下返回详细错误信息
    error_data = None
    if DEBUG_MODE:
        error_data = {
            "error_type": type(exc).__name__,
            "error_detail": str(exc),
            # 格式化异常信息为字符串，方便日志记录和调试
            "traceback": traceback.format_exc(),
            "path": str(request.url)
        }

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": "数据库操作失败，请稍后重试",
            "data": error_data
        }
    )


async def general_exception_handler(request: Request, exc: Exception):
    """
    处理所有未捕获的异常
    """
    logger.error(
        "Unhandled error while handling %s",
        request.url,
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    # 开发模式下返回详细错误信息
    error_data = None
    if DEBUG_MODE:
        error_data = {
            "error_type": type(exc).__name__,
            "error_detail": str(exc),
            # 格式化异常信息为字符串，方便日志记录和调试
            "traceback": traceback.format_exc(),
            "path": str(request.url)
        }

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "data": error_data
        }
    )

