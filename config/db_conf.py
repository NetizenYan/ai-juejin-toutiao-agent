import os
from urllib.parse import quote_plus

from config.env_loader import load_project_env
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

load_project_env()


def _build_database_url() -> str:
    explicit = os.getenv("ASYNC_DATABASE_URL") or os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    driver = os.getenv("MYSQL_DRIVER", "mysql+aiomysql")
    user = os.getenv("MYSQL_USER") or os.getenv("DB_USER", "news_app")
    password = os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD", "")
    host = os.getenv("MYSQL_HOST") or os.getenv("DB_HOST", "localhost")
    port = os.getenv("MYSQL_PORT") or os.getenv("DB_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE") or os.getenv("DB_DATABASE", "news_app")
    charset = os.getenv("MYSQL_CHARSET", "utf8mb4")

    auth = quote_plus(user)
    if password:
        auth = f"{auth}:{quote_plus(password)}"
    return f"{driver}://{auth}@{host}:{port}/{database}?charset={charset}"


# 数据库 URL。真实密码只允许来自环境变量或外部 secret 注入。
ASYNC_DATABASE_URL = _build_database_url()

# 创建异步引擎
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,  # 关闭 SQL 日志：MCP server 走 stdio JSON-RPC，stdout 不能混入日志
    pool_size=10,  # 设置连接池中保持的持久连接数
    max_overflow=20  # 设置连接池允许创建的额外连接数
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# 依赖项，用于获取数据库会话
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
