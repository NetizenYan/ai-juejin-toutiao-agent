import json
import os
from typing import Any

import redis.asyncio as redis

from config.env_loader import load_project_env


load_project_env()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None


redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True,
)


async def get_cache(key: str) -> str | None:
    try:
        return await redis_client.get(key)
    except Exception:
        return None


async def get_json_cache(key: str) -> Any | None:
    data = await get_cache(key)
    if not data:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


async def set_cache(key: str, value: Any, expire: int = 3600) -> bool:
    try:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        await redis_client.setex(key, expire, value)
        return True
    except Exception:
        return False
