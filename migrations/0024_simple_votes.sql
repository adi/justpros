-- Simplify voting: binary -1/+1 replacing 7-point scale (-3 to +3)

-- Normalize existing votes: anything negative becomes -1, anything positive becomes +1
UPDATE post_votes SET value = -1 WHERE value < 0;
UPDATE post_votes SET value = 1 WHERE value > 0;

UPDATE fact_votes SET value = -1 WHERE value < 0;
UPDATE fact_votes SET value = 1 WHERE value > 0;

-- Update post_votes constraint
ALTER TABLE post_votes DROP CONSTRAINT post_votes_value_check;
ALTER TABLE post_votes ADD CONSTRAINT post_votes_value_check CHECK (value IN (-1, 1));

-- Update fact_votes constraint
ALTER TABLE fact_votes DROP CONSTRAINT fact_votes_value_check;
ALTER TABLE fact_votes ADD CONSTRAINT fact_votes_value_check CHECK (value IN (-1, 1));

-- Add separate upvote/downvote count columns to posts
ALTER TABLE posts ADD COLUMN upvote_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE posts ADD COLUMN downvote_count INTEGER NOT NULL DEFAULT 0;

-- Populate the new columns from existing votes
UPDATE posts SET
    upvote_count = COALESCE((SELECT COUNT(*) FROM post_votes WHERE post_id = posts.id AND value = 1), 0),
    downvote_count = COALESCE((SELECT COUNT(*) FROM post_votes WHERE post_id = posts.id AND value = -1), 0);

-- Add separate upvote/downvote count columns to facts
ALTER TABLE facts ADD COLUMN upvote_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE facts ADD COLUMN downvote_count INTEGER NOT NULL DEFAULT 0;

-- Populate the new columns from existing votes
UPDATE facts SET
    upvote_count = COALESCE((SELECT COUNT(*) FROM fact_votes WHERE fact_id = facts.id AND value = 1), 0),
    downvote_count = COALESCE((SELECT COUNT(*) FROM fact_votes WHERE fact_id = facts.id AND value = -1), 0);
