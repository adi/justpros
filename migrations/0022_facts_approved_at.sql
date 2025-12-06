-- Add approved_at column to facts for early approval by subject
ALTER TABLE facts ADD COLUMN approved_at TIMESTAMPTZ;
