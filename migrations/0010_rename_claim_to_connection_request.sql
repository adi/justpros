-- Migration: Rename 'claim' to 'connection_request'
-- This prepares for separating connections (messaging) from claims (reputation)

-- Drop the check constraint first
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_kind_check;

-- Update existing 'claim' values to 'connection_request'
UPDATE messages SET kind = 'connection_request' WHERE kind = 'claim';

-- Add the new check constraint
ALTER TABLE messages ADD CONSTRAINT messages_kind_check
    CHECK (kind IN ('connection_request', 'confirm', 'text'));

-- Update the index for finding pending connection requests
DROP INDEX IF EXISTS idx_messages_claims;
CREATE INDEX idx_messages_connection_requests ON messages(receiver_id, kind, created_at)
    WHERE kind = 'connection_request';
