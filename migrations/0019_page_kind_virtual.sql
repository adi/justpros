-- Migration: Rename page kind 'other' to 'virtual'
-- 'virtual' is for bots, AI personas, fictional characters, etc.

-- Update existing pages with 'other' kind to 'virtual'
UPDATE pages SET kind = 'virtual' WHERE kind = 'other';

-- Update the check constraint
ALTER TABLE pages DROP CONSTRAINT pages_kind_check;
ALTER TABLE pages ADD CONSTRAINT pages_kind_check CHECK (kind IN ('company', 'event', 'product', 'community', 'virtual'));
