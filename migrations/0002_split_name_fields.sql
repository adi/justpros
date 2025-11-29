-- Split single name column into first_name, middle_name, last_name

ALTER TABLE users ADD COLUMN first_name VARCHAR(50);
ALTER TABLE users ADD COLUMN middle_name VARCHAR(50);
ALTER TABLE users ADD COLUMN last_name VARCHAR(50);

-- Migrate existing data: put entire name in first_name, use placeholder for last_name
UPDATE users SET first_name = name, last_name = '' WHERE name IS NOT NULL;

-- Make first_name and last_name required
ALTER TABLE users ALTER COLUMN first_name SET NOT NULL;
ALTER TABLE users ALTER COLUMN last_name SET NOT NULL;

-- Drop old name column
ALTER TABLE users DROP COLUMN name;
