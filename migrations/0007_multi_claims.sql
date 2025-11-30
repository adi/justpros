-- Migration: Allow multiple claims per user pair
-- Previously, only one claim was allowed between any two users.
-- Now users can send multiple claims (rate limited to 3/day per pair).

-- Remove the unique constraint to allow multiple claims per pair
ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_from_user_id_to_user_id_key;

-- Add index for efficient pair lookups (replaces the unique constraint's implicit index)
CREATE INDEX IF NOT EXISTS idx_conn_user_pair ON connections(from_user_id, to_user_id);

-- Create rate limiting log table for tracking claims per pair
CREATE TABLE IF NOT EXISTS connection_claims_log (
    id SERIAL PRIMARY KEY,
    from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for efficient rate limit lookups
CREATE INDEX IF NOT EXISTS idx_claims_log_pair_time ON connection_claims_log(from_user_id, to_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_claims_log_from_time ON connection_claims_log(from_user_id, created_at);
