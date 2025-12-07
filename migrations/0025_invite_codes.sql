-- Invite codes for referral-based connections
-- When a user signs up through an invite link, a connection request is auto-created

CREATE TABLE invite_codes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code VARCHAR(32) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT invite_codes_user_unique UNIQUE (user_id)
);

CREATE INDEX idx_invite_codes_code ON invite_codes(code);
CREATE INDEX idx_invite_codes_user ON invite_codes(user_id);
