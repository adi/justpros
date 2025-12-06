-- Add 'education' to page kinds
ALTER TABLE pages DROP CONSTRAINT IF EXISTS pages_kind_check;
ALTER TABLE pages ADD CONSTRAINT pages_kind_check
    CHECK (kind IN ('company', 'event', 'product', 'community', 'virtual', 'education'));
