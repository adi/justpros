-- Messages system: conversations between users

-- Conversations table: one per pair of users
CREATE TABLE conversations (
    id SERIAL PRIMARY KEY,
    user1_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user2_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_message_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Ensure user1_id < user2_id for consistent pair lookup
    CONSTRAINT conversations_user_order CHECK (user1_id < user2_id),
    UNIQUE(user1_id, user2_id)
);

CREATE INDEX idx_conv_user1 ON conversations(user1_id);
CREATE INDEX idx_conv_user2 ON conversations(user2_id);
CREATE INDEX idx_conv_last_message ON conversations(last_message_at DESC);

-- Messages table
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    read_at TIMESTAMPTZ,  -- NULL = unread
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_msg_conversation ON messages(conversation_id, created_at DESC);
CREATE INDEX idx_msg_sender ON messages(sender_id);
CREATE INDEX idx_msg_unread ON messages(conversation_id, read_at) WHERE read_at IS NULL;
