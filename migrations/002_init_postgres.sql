-- =============================================
-- Telegram Business Bot — Database Schema (PostgreSQL)
--
-- SQLite (001_init.sql) ning Postgres varianti.
-- Farqlar:
--   INTEGER (Telegram ID)  -> BIGINT (ID lar 32-bitdan katta bo'lishi mumkin)
--   TEXT (vaqt)            -> TIMESTAMPTZ (haqiqiy vaqt turi)
--   0/1 (boolean)          -> BOOLEAN
--   raw_json TEXT          -> JSONB (indekslasa va so'rov qilsa bo'ladi)
--   AUTOINCREMENT          -> BIGSERIAL
--   datetime('now')        -> now()
-- =============================================

-- Botni ulagan xodimlar (business connections)
CREATE TABLE IF NOT EXISTS connections (
    id              TEXT PRIMARY KEY,            -- business_connection_id
    user_id         BIGINT NOT NULL,             -- xodimning Telegram user id
    user_chat_id    BIGINT,                      -- xodim bilan shaxsiy chat id
    username        TEXT,
    first_name      TEXT,
    can_reply       BOOLEAN,
    is_enabled      BOOLEAN DEFAULT TRUE,
    connected_at    TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Kashf qilingan chatlar (xabar kelganda avtomatik yaratiladi)
CREATE TABLE IF NOT EXISTS chats (
    connection_id   TEXT,
    chat_id         BIGINT,
    chat_type       TEXT,
    title           TEXT,
    username        TEXT,
    first_seen      TIMESTAMPTZ DEFAULT now(),
    last_message_at TIMESTAMPTZ,
    message_count   INTEGER DEFAULT 0,
    PRIMARY KEY (connection_id, chat_id)
);

-- Hamma xabarlar
CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    connection_id   TEXT,
    chat_id         BIGINT,
    from_user_id    BIGINT,
    from_user_name  TEXT,
    message_id      BIGINT,
    direction       TEXT,                        -- 'incoming' | 'outgoing'
    content_type    TEXT,                        -- 'text' | 'photo' | 'voice' | ...
    text            TEXT,                        -- text yoki caption (toza matn)
    media_file_id   TEXT,
    media_file_name TEXT,
    media_mime      TEXT,
    media_duration  INTEGER,
    is_edited       BOOLEAN DEFAULT FALSE,
    is_deleted      BOOLEAN DEFAULT FALSE,
    raw_json        JSONB,                       -- butun update JSON (JSONB)
    tg_date         TIMESTAMPTZ,                 -- Telegram vaqti
    created_at      TIMESTAMPTZ DEFAULT now(),
    analyzed        BOOLEAN DEFAULT FALSE        -- AI worker uchun
);

-- Indekslar
CREATE INDEX IF NOT EXISTS idx_messages_conn_chat ON messages (connection_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_created   ON messages (created_at);
CREATE INDEX IF NOT EXISTS idx_messages_analyzed  ON messages (analyzed);

-- Botga /start bosgan oddiy foydalanuvchilar (reklama yuborish uchun)
CREATE TABLE IF NOT EXISTS bot_users (
    user_id         BIGINT PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    language_code   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
