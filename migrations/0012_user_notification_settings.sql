-- Add notification settings to users table
ALTER TABLE users ADD COLUMN notify_mentions BOOLEAN NOT NULL DEFAULT false;
