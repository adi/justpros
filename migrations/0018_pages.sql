-- Migration: Pages Feature
-- Creates pages, page_editors, page_follows tables and adds page_id to posts

-- Pages table
CREATE TABLE pages (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(30) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    kind VARCHAR(30) NOT NULL DEFAULT 'other',
    headline VARCHAR(200),
    description TEXT,
    icon_path VARCHAR(500),
    cover_path VARCHAR(500),
    owner_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT pages_kind_check CHECK (kind IN ('company', 'event', 'product', 'community', 'other')),
    CONSTRAINT pages_handle_format CHECK (handle ~ '^[a-z0-9_]+$')
);

CREATE INDEX idx_pages_handle ON pages(handle);
CREATE INDEX idx_pages_owner ON pages(owner_id);
CREATE INDEX idx_pages_kind ON pages(kind);

-- Page editors (users who can post as the page)
CREATE TABLE page_editors (
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invited_by INTEGER NOT NULL REFERENCES users(id),
    invited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,  -- NULL = pending invitation

    PRIMARY KEY (page_id, user_id)
);

CREATE INDEX idx_page_editors_user ON page_editors(user_id);
CREATE INDEX idx_page_editors_pending ON page_editors(user_id) WHERE accepted_at IS NULL;

-- Page follows (users following pages)
CREATE TABLE page_follows (
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (page_id, user_id)
);

CREATE INDEX idx_page_follows_user ON page_follows(user_id);
CREATE INDEX idx_page_follows_page ON page_follows(page_id);

-- Add page_id to posts for Page posts
ALTER TABLE posts ADD COLUMN page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE;
CREATE INDEX idx_posts_page ON posts(page_id, created_at DESC) WHERE page_id IS NOT NULL;
