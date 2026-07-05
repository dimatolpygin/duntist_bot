-- Видео-инструкция «как загружать файлы», которую бот показывает технику
-- в начале «Нового заказа». Singleton: всегда строка с id = 1.
-- Храним file_id (нативное видео 120 МБ отдаётся только по file_id), тип и подпись.
CREATE TABLE IF NOT EXISTS instruction_video (
    id          SMALLINT    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    file_id     TEXT        NOT NULL,               -- Telegram file_id видео/документа
    is_video    BOOLEAN     NOT NULL DEFAULT TRUE,  -- TRUE = video, FALSE = document
    caption     TEXT,                               -- подпись под видео (HTML)
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  BIGINT                              -- tg_id админа, задавшего видео
);
