-- =============================================
-- Telegram Business Bot — Database Schema (SQLite)
-- =============================================

-- Botni ulagan xodimlar (business connections)
CREATE TABLE IF NOT EXISTS connections (
    id              TEXT PRIMARY KEY,            -- business_connection_id
    user_id         INTEGER NOT NULL,            -- xodimning Telegram user id
    user_chat_id    INTEGER,                     -- xodim bilan shaxsiy chat id
    username        TEXT,
    first_name      TEXT,
    can_reply       INTEGER,                     -- 0/1 (boolean)
    is_enabled      INTEGER DEFAULT 1,           -- 0/1
    connected_at    TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Kashf qilingan chatlar (xabar kelganda avtomatik yaratiladi)
CREATE TABLE IF NOT EXISTS chats (
    connection_id   TEXT,
    chat_id         INTEGER,
    chat_type       TEXT,
    title           TEXT,
    username        TEXT,
    first_seen      TEXT DEFAULT (datetime('now')),
    last_message_at TEXT,
    message_count   INTEGER DEFAULT 0,
    PRIMARY KEY (connection_id, chat_id)
);

-- Hamma xabarlar
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id   TEXT,
    chat_id         INTEGER,
    from_user_id    INTEGER,
    from_user_name  TEXT,
    message_id      INTEGER,
    direction       TEXT,                        -- 'incoming' | 'outgoing'
    content_type    TEXT,                         -- 'text' | 'photo' | 'voice' | ...
    text            TEXT,                         -- text yoki caption (toza matn)
    media_file_id   TEXT,
    media_file_name TEXT,
    media_mime      TEXT,
    media_duration  INTEGER,
    is_edited       INTEGER DEFAULT 0,           -- 0/1
    is_deleted      INTEGER DEFAULT 0,           -- 0/1
    raw_json        TEXT,                         -- butun update JSON (TEXT sifatida)
    tg_date         TEXT,                         -- Telegram vaqti (ISO format)
    created_at      TEXT DEFAULT (datetime('now')),
    analyzed        INTEGER DEFAULT 0             -- AI worker uchun (0/1)
);

-- Indekslar
CREATE INDEX IF NOT EXISTS idx_messages_conn_chat ON messages (connection_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_created   ON messages (created_at);
CREATE INDEX IF NOT EXISTS idx_messages_analyzed  ON messages (analyzed);

-- Botga /start bosgan oddiy foydalanuvchilar (reklama yuborish uchun)
CREATE TABLE IF NOT EXISTS bot_users (
    user_id         INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    language_code   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

