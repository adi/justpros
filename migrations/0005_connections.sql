-- Connections system: claim-based professional connections

-- Add trustworthiness and karma columns to users
ALTER TABLE users ADD COLUMN trustworthiness REAL DEFAULT 1.0;
ALTER TABLE users ADD COLUMN karma_points INTEGER DEFAULT 15;
ALTER TABLE users ADD COLUMN karma_last_regen TIMESTAMPTZ DEFAULT NOW();

-- Connections table: relationship claims between users
CREATE TABLE connections (
    id SERIAL PRIMARY KEY,
    from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    claim TEXT NOT NULL,  -- "Was my manager at Google" or "Worked together on Project X"
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'confirmed', 'ignored'
    created_at TIMESTAMPTZ DEFAULT NOW(),  -- used for time decay (never changes)
    confirmed_at TIMESTAMPTZ,
    ignored_at TIMESTAMPTZ,  -- when manually ignored or auto-ignored after 30 days

    UNIQUE(from_user_id, to_user_id)  -- one connection per pair
);

CREATE INDEX idx_conn_from_user ON connections(from_user_id);
CREATE INDEX idx_conn_to_user ON connections(to_user_id);
CREATE INDEX idx_conn_status ON connections(status);

-- Connection votes: mutual connections can vote on claim credibility
CREATE TABLE connection_votes (
    id SERIAL PRIMARY KEY,
    connection_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    voter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vote SMALLINT NOT NULL,  -- +1 (credible) or -1 (not credible)
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(connection_id, voter_id)
);

CREATE INDEX idx_cv_connection ON connection_votes(connection_id);
CREATE INDEX idx_cv_voter ON connection_votes(voter_id);

-- Rate limiting: track claim attempts
CREATE TABLE connection_claims_log (
    id SERIAL PRIMARY KEY,
    from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ccl_from_user_date ON connection_claims_log(from_user_id, created_at);
CREATE INDEX idx_ccl_pair_date ON connection_claims_log(from_user_id, to_user_id, created_at);

-- Abuse reports: LLM-evaluated reports
CREATE TABLE abuse_reports (
    id SERIAL PRIMARY KEY,
    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reported_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    connection_id INTEGER REFERENCES connections(id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'upheld', 'dismissed'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    llm_reasoning TEXT  -- LLM's explanation for the decision
);

CREATE INDEX idx_ar_reported ON abuse_reports(reported_user_id);
CREATE INDEX idx_ar_status ON abuse_reports(status);
CREATE INDEX idx_ar_reporter_date ON abuse_reports(reporter_id, created_at);
