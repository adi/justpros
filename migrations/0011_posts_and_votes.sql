-- Posts table (includes both top-level posts and comments)
CREATE TABLE posts (
    id SERIAL PRIMARY KEY,
    author_id INTEGER NOT NULL REFERENCES users(id),
    content TEXT NOT NULL,
    visibility VARCHAR(20) NOT NULL DEFAULT 'connections',
    reply_to_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    root_post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,

    -- Cached vote counts for performance
    upvote_count INTEGER NOT NULL DEFAULT 0,
    downvote_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT posts_visibility_check CHECK (visibility IN ('public', 'connections')),
    CONSTRAINT posts_content_length CHECK (char_length(content) <= 2000)
);

-- Indexes for feed queries
CREATE INDEX idx_posts_feed ON posts(created_at DESC) WHERE reply_to_id IS NULL;
CREATE INDEX idx_posts_author ON posts(author_id, created_at DESC);
CREATE INDEX idx_posts_replies ON posts(reply_to_id, created_at ASC) WHERE reply_to_id IS NOT NULL;
CREATE INDEX idx_posts_root ON posts(root_post_id);
CREATE INDEX idx_posts_public_feed ON posts(created_at DESC) WHERE reply_to_id IS NULL AND visibility = 'public';

-- Votes table
CREATE TABLE post_votes (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    value SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (post_id, user_id),
    CONSTRAINT post_votes_value_check CHECK (value IN (-1, 1))
);

CREATE INDEX idx_post_votes_user ON post_votes(user_id);
