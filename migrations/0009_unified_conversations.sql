-- Migration: Unified Conversations Model
-- Simplified: no conversations table, derived from messages
-- Connection status derived from existence of 'confirm' message

-- Drop old tables (starting fresh as per plan)
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS conversations CASCADE;
DROP TABLE IF EXISTS connections CASCADE;
DROP TABLE IF EXISTS conversation_reads CASCADE;
DROP TABLE IF EXISTS abuse_reports CASCADE;
DROP TABLE IF EXISTS connection_votes CASCADE;
DROP TABLE IF EXISTS connection_claims_log CASCADE;

-- Messages: the core entity, conversations derived from sender/receiver pairs
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(20) NOT NULL DEFAULT 'text',
    sender_id INTEGER NOT NULL REFERENCES users(id),
    receiver_id INTEGER NOT NULL REFERENCES users(id),
    content TEXT,  -- plain text for all message kinds
    reply_to INTEGER REFERENCES messages(id),  -- for threading context
    sender_deleted TIMESTAMPTZ,  -- soft delete timestamp for sender
    receiver_deleted TIMESTAMPTZ,  -- soft delete timestamp for receiver
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT messages_kind_check CHECK (kind IN ('claim', 'confirm', 'text'))
);

-- Index for fetching messages in a conversation (either direction)
CREATE INDEX idx_messages_sender_receiver ON messages(sender_id, receiver_id, created_at DESC);
CREATE INDEX idx_messages_receiver_sender ON messages(receiver_id, sender_id, created_at DESC);

-- Index for finding pending claims (claims without a confirm response)
CREATE INDEX idx_messages_claims ON messages(receiver_id, kind, created_at)
    WHERE kind = 'claim';

-- Read tracking: one row per user per conversation partner
-- We derive the conversation partner from the last_read_message
-- The unique constraint ensures one read marker per user per conversation
CREATE TABLE conversation_reads (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_read_message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE
);

-- Index for quick lookup by user
CREATE INDEX idx_conversation_reads_user ON conversation_reads(user_id);
CREATE UNIQUE INDEX idx_conversation_reads_unique ON conversation_reads(user_id, last_read_message_id);

-- Abuse reports: per conversation, requires reason
CREATE TABLE abuse_reports (
    id SERIAL PRIMARY KEY,
    reporter_id INTEGER NOT NULL REFERENCES users(id),
    reported_user_id INTEGER NOT NULL REFERENCES users(id),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_abuse_reports_reporter ON abuse_reports(reporter_id, created_at DESC);
CREATE INDEX idx_abuse_reports_reported ON abuse_reports(reported_user_id);
