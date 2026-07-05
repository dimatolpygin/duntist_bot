-- Начальная схема бота приёма заказов.
-- Таблицы создаются без указания схемы — они попадают в нашу схему благодаря search_path,
-- настроенному в пуле соединений (см. src/db.py). Существующие схемы не затрагиваются.

-- Заказ: одна карточка от техника. id = номер заказа (последовательный).
CREATE TABLE IF NOT EXISTS orders (
    id            BIGSERIAL   PRIMARY KEY,             -- номер заказа
    tg_id         BIGINT      NOT NULL,                -- автор (техник/заказчик)
    username      TEXT,
    first_name    TEXT,
    client_name   TEXT,                                -- имя клиента (спрашивает бот)
    quantity      TEXT,                                -- количество/описание, напр. "ц/л 4шт, 4 МК"
    status        TEXT        NOT NULL DEFAULT 'new',  -- new → completed (базовая версия)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);

-- Файлы, приложенные к заказу (любое количество, любые типы).
CREATE TABLE IF NOT EXISTS order_files (
    id             BIGSERIAL   PRIMARY KEY,
    order_id       BIGINT      NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    file_id        TEXT        NOT NULL,   -- Telegram file_id (для пересылки/копии)
    file_unique_id TEXT,
    file_type      TEXT        NOT NULL,   -- document / photo / video / audio / ...
    file_name      TEXT,
    mime_type      TEXT,
    file_size      BIGINT,                 -- размер в байтах (для обработки больших файлов)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_order_files_order ON order_files (order_id);
