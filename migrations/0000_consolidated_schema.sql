-- Consolidated Schema for JustPros
-- This file documents the current database structure as of migration 0017
-- DO NOT RUN THIS FILE - it's for reference only
-- The actual migrations (0001-0017) should be used for database setup

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
-- POSTS TABLE
-- User posts with visibility controls and comment threading
-- ============================================================================
CREATE TABLE posts (
    id SERIAL PRIMARY KEY,
    author_id INTEGER NOT NULL REFERENCES users(id),
    content TEXT NOT NULL,
    visibility VARCHAR(20) NOT NULL DEFAULT 'connections',
    reply_to_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    root_post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    comment_count INTEGER NOT NULL DEFAULT 0,
    vote_sum INTEGER NOT NULL DEFAULT 0,
    vote_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT posts_content_length CHECK (char_length(content) <= 2000),
    CONSTRAINT posts_visibility_check CHECK (visibility IN ('public', 'connections'))
);

CREATE INDEX idx_posts_author ON posts(author_id, created_at DESC);
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
-- User votes on posts (scaled -3 to +3 based on trustworthiness)
-- ============================================================================
CREATE TABLE post_votes (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    value SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (post_id, user_id),
    CONSTRAINT post_votes_value_check CHECK (value >= -3 AND value <= 3)
);

CREATE INDEX idx_post_votes_user ON post_votes(user_id);


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
