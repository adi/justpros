-- Consolidated Schema for JustPros
-- This file documents the current database structure as of migration 0025
-- DO NOT RUN THIS FILE - it's for reference only
-- The actual migrations (0001-0025) should be used for database setup

-- ============================================================================
-- USERS TABLE
-- Core user accounts with profile information
-- ============================================================================
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(30) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    middle_name VARCHAR(50),
    last_name VARCHAR(50) NOT NULL,
    headline VARCHAR(200),
    avatar_path VARCHAR(500),
    cover_path VARCHAR(255),
    skills TEXT[] DEFAULT '{}',
    verified BOOLEAN DEFAULT false,
    verification_token VARCHAR(64),
    verification_token_expires TIMESTAMPTZ,
    reset_token VARCHAR(64),
    reset_token_expires TIMESTAMPTZ,
    trustworthiness REAL DEFAULT 1.0,
    karma_points INTEGER DEFAULT 15,
    karma_last_regen TIMESTAMPTZ DEFAULT NOW(),
    notify_mentions BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_handle ON users(handle);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_skills ON users USING GIN(skills);


-- ============================================================================
-- CONNECTIONS TABLE
-- Tracks connections between users (pending, confirmed, ignored)
-- Uses ordered pair constraint (user1_id < user2_id) for unique lookups
-- ============================================================================
CREATE TABLE connections (
    id SERIAL PRIMARY KEY,
    user1_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user2_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    requested_by INTEGER NOT NULL REFERENCES users(id),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    responded_at TIMESTAMPTZ,

    CONSTRAINT connections_ordered_pair CHECK (user1_id < user2_id),
    CONSTRAINT connections_unique_pair UNIQUE (user1_id, user2_id),
    CONSTRAINT connections_status_check CHECK (status IN ('pending', 'confirmed', 'ignored'))
);

CREATE INDEX idx_connections_user1 ON connections(user1_id, status);
CREATE INDEX idx_connections_user2 ON connections(user2_id, status);
CREATE INDEX idx_connections_pending ON connections(status, requested_at) WHERE status = 'pending';


-- ============================================================================
-- MESSAGES TABLE
-- Direct messages between connected users (text only, no connection requests)
-- ============================================================================
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    sender_id INTEGER NOT NULL REFERENCES users(id),
    receiver_id INTEGER NOT NULL REFERENCES users(id),
    content TEXT,
    reply_to INTEGER REFERENCES messages(id),
    sender_deleted TIMESTAMPTZ,
    receiver_deleted TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_sender_receiver ON messages(sender_id, receiver_id, created_at DESC);
CREATE INDEX idx_messages_receiver_sender ON messages(receiver_id, sender_id, created_at DESC);


-- ============================================================================
-- CONVERSATION_READS TABLE
-- Tracks last read message per conversation for unread counts
-- ============================================================================
CREATE TABLE conversation_reads (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    other_user_id INTEGER NOT NULL REFERENCES users(id),
    last_read_message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_conversation_reads_unique ON conversation_reads(user_id, other_user_id);
CREATE INDEX idx_conversation_reads_user ON conversation_reads(user_id);


-- ============================================================================
-- PAGES TABLE
-- Organization/entity profiles (companies, events, products, communities, etc.)
-- ============================================================================
CREATE TABLE pages (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    tagline VARCHAR(200),
    description TEXT,
    icon_path VARCHAR(500),
    cover_path VARCHAR(500),
    website VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pages_kind_check CHECK (kind IN ('company', 'event', 'product', 'community', 'virtual', 'education'))
);

CREATE INDEX idx_pages_handle ON pages(handle);
CREATE INDEX idx_pages_kind ON pages(kind);


-- ============================================================================
-- PAGE_EDITORS TABLE
-- Users who can manage and post on behalf of pages
-- ============================================================================
CREATE TABLE page_editors (
    id SERIAL PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'editor',
    invited_by INTEGER REFERENCES users(id),
    invited_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,

    CONSTRAINT page_editors_unique UNIQUE (page_id, user_id),
    CONSTRAINT page_editors_role_check CHECK (role IN ('owner', 'editor'))
);

CREATE INDEX idx_page_editors_page ON page_editors(page_id);
CREATE INDEX idx_page_editors_user ON page_editors(user_id);


-- ============================================================================
-- PAGE_FOLLOWS TABLE
-- Users following pages to see their posts in feed
-- ============================================================================
CREATE TABLE page_follows (
    id SERIAL PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT page_follows_unique UNIQUE (page_id, user_id)
);

CREATE INDEX idx_page_follows_page ON page_follows(page_id);
CREATE INDEX idx_page_follows_user ON page_follows(user_id);


-- ============================================================================
-- POSTS TABLE
-- User posts with visibility controls and comment threading
-- Can be posted by users or on behalf of pages
-- ============================================================================
CREATE TABLE posts (
    id SERIAL PRIMARY KEY,
    author_id INTEGER NOT NULL REFERENCES users(id),
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    visibility VARCHAR(20) NOT NULL DEFAULT 'connections',
    reply_to_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    root_post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    comment_count INTEGER NOT NULL DEFAULT 0,
    vote_sum INTEGER NOT NULL DEFAULT 0,
    vote_count INTEGER NOT NULL DEFAULT 0,
    upvote_count INTEGER NOT NULL DEFAULT 0,
    downvote_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT posts_content_length CHECK (char_length(content) <= 2000),
    CONSTRAINT posts_visibility_check CHECK (visibility IN ('public', 'connections'))
);

CREATE INDEX idx_posts_author ON posts(author_id, created_at DESC);
CREATE INDEX idx_posts_page ON posts(page_id, created_at DESC) WHERE page_id IS NOT NULL;
CREATE INDEX idx_posts_feed ON posts(created_at DESC) WHERE reply_to_id IS NULL;
CREATE INDEX idx_posts_public_feed ON posts(created_at DESC) WHERE reply_to_id IS NULL AND visibility = 'public';
CREATE INDEX idx_posts_replies ON posts(reply_to_id, created_at) WHERE reply_to_id IS NOT NULL;
CREATE INDEX idx_posts_root ON posts(root_post_id);


-- ============================================================================
-- POST_MEDIA TABLE
-- Media attachments for posts (images and videos)
-- ============================================================================
CREATE TABLE post_media (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    media_path TEXT NOT NULL,
    media_type VARCHAR(20) NOT NULL,
    display_order SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT post_media_type_check CHECK (media_type IN ('image', 'video'))
);

CREATE INDEX idx_post_media_post ON post_media(post_id, display_order);


-- ============================================================================
-- POST_VOTES TABLE
-- Binary user votes on posts (-1 downvote, +1 upvote)
-- ============================================================================
CREATE TABLE post_votes (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    value SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (post_id, user_id),
    CONSTRAINT post_votes_value_check CHECK (value IN (-1, 1))
);

CREATE INDEX idx_post_votes_user ON post_votes(user_id);


-- ============================================================================
-- FACTS TABLE
-- Professional facts about users or pages (e.g., "I worked at @company")
-- ============================================================================
CREATE TABLE facts (
    id SERIAL PRIMARY KEY,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    subject_page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    template_id VARCHAR(50),
    content TEXT NOT NULL,
    mentions JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    public_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '72 hours',
    approved_at TIMESTAMPTZ,
    vetoed_at TIMESTAMPTZ,
    vote_sum INTEGER NOT NULL DEFAULT 0,
    vote_count INTEGER NOT NULL DEFAULT 0,
    upvote_count INTEGER NOT NULL DEFAULT 0,
    downvote_count INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT facts_one_subject CHECK (
        (subject_user_id IS NOT NULL AND subject_page_id IS NULL) OR
        (subject_user_id IS NULL AND subject_page_id IS NOT NULL)
    ),
    CONSTRAINT facts_not_self CHECK (author_id != subject_user_id)
);

CREATE INDEX idx_facts_author ON facts(author_id);
CREATE INDEX idx_facts_subject_user ON facts(subject_user_id) WHERE subject_user_id IS NOT NULL;
CREATE INDEX idx_facts_subject_page ON facts(subject_page_id) WHERE subject_page_id IS NOT NULL;
CREATE INDEX idx_facts_public ON facts(public_at) WHERE vetoed_at IS NULL;


-- ============================================================================
-- FACT_VOTES TABLE
-- Binary user votes on facts (-1 downvote, +1 upvote)
-- ============================================================================
CREATE TABLE fact_votes (
    fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    value SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (fact_id, user_id),
    CONSTRAINT fact_votes_value_check CHECK (value IN (-1, 1))
);

CREATE INDEX idx_fact_votes_user ON fact_votes(user_id);


-- ============================================================================
-- INVITE_CODES TABLE
-- Personal invite codes for user referrals
-- ============================================================================
CREATE TABLE invite_codes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code VARCHAR(20) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT invite_codes_user_unique UNIQUE (user_id)
);

CREATE INDEX idx_invite_codes_code ON invite_codes(code);


-- ============================================================================
-- ABUSE_REPORTS TABLE
-- Reports for user abuse (messaging context)
-- ============================================================================
CREATE TABLE abuse_reports (
    id SERIAL PRIMARY KEY,
    reporter_id INTEGER NOT NULL REFERENCES users(id),
    reported_user_id INTEGER NOT NULL REFERENCES users(id),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_abuse_reports_reporter ON abuse_reports(reporter_id, created_at DESC);
CREATE INDEX idx_abuse_reports_reported ON abuse_reports(reported_user_id);


-- ============================================================================
-- POST_ABUSE_REPORTS TABLE
-- Reports for post abuse
-- ============================================================================
CREATE TABLE post_abuse_reports (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT post_abuse_reports_post_id_reporter_id_key UNIQUE (post_id, reporter_id)
);

CREATE INDEX idx_post_abuse_reports_post_id ON post_abuse_reports(post_id);
CREATE INDEX idx_post_abuse_reports_created_at ON post_abuse_reports(created_at DESC);


-- ============================================================================
-- MIGRATIONS TABLE
-- Tracks applied migrations (managed by app/migrate.py)
-- ============================================================================
CREATE TABLE _migrations (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);
