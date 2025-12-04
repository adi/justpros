-- Post abuse reports table for posts/comments
CREATE TABLE IF NOT EXISTS post_abuse_reports (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(post_id, reporter_id)
);

CREATE INDEX IF NOT EXISTS idx_post_abuse_reports_post_id ON post_abuse_reports(post_id);
CREATE INDEX IF NOT EXISTS idx_post_abuse_reports_created_at ON post_abuse_reports(created_at DESC);
