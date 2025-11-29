-- JustPros Database Schema

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(30) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    headline VARCHAR(200),
    avatar_url VARCHAR(500),
    skills TEXT[] DEFAULT '{}',
    verified BOOLEAN DEFAULT FALSE,
    verification_token VARCHAR(64),
    verification_token_expires TIMESTAMPTZ,
    reset_token VARCHAR(64),
    reset_token_expires TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_handle ON users(handle);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_skills ON users USING GIN(skills);
