"""Конфигурация проекта. Все значения берутся из переменных окружения (.env)."""
from __future__ import annotations

import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram
    bot_token: str
    # Закрытая группа «Город», куда уходят карточки заказов и файлы.
    # Числовой id вида -1001234567890 (бот должен состоять в группе).
    group_id: str
    # ID администраторов через запятую (необязательно; для сервисных команд).
    admin_ids: str = ""

    # БД
    database_url: str
    db_schema: str = "zarub"

    # Redis (FSM-хранилище сценария заказа)
    redis_url: str = "redis://localhost:6379/0"

    # S3 (Beget) — используется на этапе больших файлов. На старте необязательно.
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_public_base_url: str = ""

    # Прочее
    log_level: str = "INFO"

    @field_validator("db_schema")
    @classmethod
    def _validate_schema(cls, v: str) -> str:
        # Защита от SQL-инъекции: имя схемы подставляется в DDL напрямую.
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", v):
            raise ValueError(f"Недопустимое имя схемы: {v}")
        return v

    @property
    def group_chat_id(self) -> int:
        """id группы «Город» как целое (для вызовов Telegram API)."""
        return int(self.group_id)

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.replace(" ", "").split(",") if x]


settings = Settings()
