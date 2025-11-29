-- Rename avatar_url to avatar_path since we now store only the path
ALTER TABLE users RENAME COLUMN avatar_url TO avatar_path;
