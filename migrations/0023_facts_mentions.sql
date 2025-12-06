-- Add mentions column to facts for linkable @mentions
-- Stores JSON mapping handle -> {type: "user"|"page", name: "display name"}
ALTER TABLE facts ADD COLUMN mentions JSONB DEFAULT '{}';
