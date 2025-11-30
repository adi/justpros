-- Migration: Split claim into subject and body
-- Subject: short description (e.g., "Worked together")
-- Body: optional longer explanation with rich text

-- Rename claim to subject
ALTER TABLE connections RENAME COLUMN claim TO subject;

-- Add body column for rich text content
ALTER TABLE connections ADD COLUMN body TEXT;
