-- Post media table for image attachments
CREATE TABLE post_media (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    media_path TEXT NOT NULL,
    media_type VARCHAR(20) NOT NULL,
    display_order SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT post_media_type_check CHECK (media_type IN ('image'))
);

-- Index for fetching media by post
CREATE INDEX idx_post_media_post ON post_media(post_id, display_order);
