-- Migration: Separate Connections from Messages
-- Creates a dedicated connections table for O(1) connection lookups
-- Simplifies messages table to text-only

-- Create dedicated connections table with proper indexing
CREATE TABLE connections (
    id SERIAL PRIMARY KEY,
    user1_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user2_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- 'pending', 'confirmed', 'ignored'
    requested_by INTEGER NOT NULL REFERENCES users(id),  -- who initiated
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    responded_at TIMESTAMPTZ,  -- when confirmed/ignored

    CONSTRAINT connections_ordered_pair CHECK (user1_id < user2_id),
    CONSTRAINT connections_unique_pair UNIQUE (user1_id, user2_id),
    CONSTRAINT connections_status_check CHECK (status IN ('pending', 'confirmed', 'ignored'))
);

-- Indexes for O(1) lookups
CREATE INDEX idx_connections_user1 ON connections(user1_id, status);
CREATE INDEX idx_connections_user2 ON connections(user2_id, status);
CREATE INDEX idx_connections_pending ON connections(status, requested_at) WHERE status = 'pending';

-- Migrate existing confirmed connections from messages table
INSERT INTO connections (user1_id, user2_id, status, requested_by, requested_at, responded_at)
SELECT DISTINCT ON (LEAST(m.sender_id, m.receiver_id), GREATEST(m.sender_id, m.receiver_id))
    LEAST(m.sender_id, m.receiver_id) as user1_id,
    GREATEST(m.sender_id, m.receiver_id) as user2_id,
    'confirmed' as status,
    COALESCE(
        (SELECT mm.sender_id FROM messages mm
         WHERE mm.kind = 'connection_request'
           AND ((mm.sender_id = m.sender_id AND mm.receiver_id = m.receiver_id)
                OR (mm.sender_id = m.receiver_id AND mm.receiver_id = m.sender_id))
         ORDER BY mm.created_at LIMIT 1),
        m.sender_id  -- fallback if no connection_request found
    ) as requested_by,
    COALESCE(
        (SELECT MIN(mm.created_at) FROM messages mm
         WHERE mm.kind = 'connection_request'
           AND ((mm.sender_id = m.sender_id AND mm.receiver_id = m.receiver_id)
                OR (mm.sender_id = m.receiver_id AND mm.receiver_id = m.sender_id))),
        m.created_at  -- fallback
    ) as requested_at,
    m.created_at as responded_at
FROM messages m
WHERE m.kind = 'confirm'
ORDER BY LEAST(m.sender_id, m.receiver_id), GREATEST(m.sender_id, m.receiver_id), m.created_at DESC;

-- Migrate pending connection requests (not yet confirmed)
INSERT INTO connections (user1_id, user2_id, status, requested_by, requested_at)
SELECT
    LEAST(m.sender_id, m.receiver_id) as user1_id,
    GREATEST(m.sender_id, m.receiver_id) as user2_id,
    CASE WHEN m.receiver_deleted IS NOT NULL THEN 'ignored' ELSE 'pending' END as status,
    m.sender_id as requested_by,
    m.created_at as requested_at
FROM messages m
WHERE m.kind = 'connection_request'
  AND NOT EXISTS (
      SELECT 1 FROM connections c
      WHERE c.user1_id = LEAST(m.sender_id, m.receiver_id)
        AND c.user2_id = GREATEST(m.sender_id, m.receiver_id)
  )
  AND m.sender_deleted IS NULL
ON CONFLICT (user1_id, user2_id) DO NOTHING;

-- Add other_user_id to conversation_reads for direct lookup
ALTER TABLE conversation_reads ADD COLUMN other_user_id INTEGER REFERENCES users(id);

-- Populate other_user_id from existing messages
UPDATE conversation_reads cr
SET other_user_id = (
    SELECT CASE
        WHEN m.sender_id = cr.user_id THEN m.receiver_id
        ELSE m.sender_id
    END
    FROM messages m
    WHERE m.id = cr.last_read_message_id
);

-- Delete orphaned conversation_reads where we couldn't determine other_user_id
DELETE FROM conversation_reads WHERE other_user_id IS NULL;

-- Make other_user_id NOT NULL after population
ALTER TABLE conversation_reads ALTER COLUMN other_user_id SET NOT NULL;

-- Add unique constraint on (user_id, other_user_id)
DROP INDEX IF EXISTS idx_conversation_reads_unique;
CREATE UNIQUE INDEX idx_conversation_reads_unique ON conversation_reads(user_id, other_user_id);

-- Delete connection-related messages (now in connections table)
DELETE FROM messages WHERE kind IN ('connection_request', 'confirm');

-- Remove kind column from messages (now only text messages)
ALTER TABLE messages DROP COLUMN kind;

-- Drop the kind-related index
DROP INDEX IF EXISTS idx_messages_claims;
