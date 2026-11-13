"""Проверка двух Redis-баз без чтения/изменения пользовательских сессий.

Использует только случайный тестовый namespace, удаляет свои ключи в finally.
Запуск внутри второго контейнера: python -m scripts.check_second_isolation.
"""
import asyncio
from uuid import uuid4
from urllib.parse import urlparse, urlunparse

from aiogram.fsm.storage.base import DefaultKeyBuilder, StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from src.config import settings
from src.prepare_second import validate_isolation


async def main() -> None:
    validate_isolation()
    parsed = urlparse(settings.redis_url)
    first = Redis.from_url(urlunparse(parsed._replace(path="/0")))
    second = Redis.from_url(settings.redis_url)
    namespace = f"readiness:{uuid4().hex}"
    stores = [RedisStorage(redis=r, key_builder=DefaultKeyBuilder(prefix=namespace))
              for r in (first, second)]
    # Одинаковые идентификаторы намеренно проверяют именно разделение Redis-баз.
    user = StorageKey(bot_id=1, chat_id=1, user_id=1)
    queue = f"{namespace}:pending_orders"
    try:
        await stores[0].set_state(user, "first")
        await stores[1].set_state(user, "second")
        await stores[0].set_data(user, {"files": ["first.stl"]})
        await stores[1].set_data(user, {"files": ["second.stl"]})
        assert await stores[0].get_state(user) == "first"
        assert await stores[1].get_state(user) == "second"
        assert await stores[0].get_data(user) == {"files": ["first.stl"]}
        assert await stores[1].get_data(user) == {"files": ["second.stl"]}
        await first.zadd(queue, {"1:1": 10})
        await second.zadd(queue, {"1:1": 20})
        await second.zrem(queue, "1:1")
        assert await first.zscore(queue, "1:1") == 10
        assert await second.zscore(queue, "1:1") is None
        await stores[1].set_state(user, None)
        assert await stores[0].get_state(user) == "first"
        print("ISOLATION_OK: FSM, файлы и таймеры одного пользователя разделены между /0 и /1")
    finally:
        for store in stores:
            await store.set_state(user, None)
            await store.set_data(user, {})
        await first.delete(queue)
        await second.delete(queue)
        await first.aclose()
        await second.aclose()


if __name__ == "__main__":
    asyncio.run(main())
