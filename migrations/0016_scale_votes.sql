-- Scale-based voting: 7-point scale (-3 to +3) replacing binary upvote/downvote

-- Modify post_votes to support -3 to +3 range
ALTER TABLE post_votes DROP CONSTRAINT post_votes_value_check;
ALTER TABLE post_votes ADD CONSTRAINT post_votes_value_check CHECK (value BETWEEN -3 AND 3);

-- Replace upvote_count/downvote_count with vote stats
ALTER TABLE posts DROP COLUMN upvote_count;
ALTER TABLE posts DROP COLUMN downvote_count;
ALTER TABLE posts ADD COLUMN vote_sum INTEGER NOT NULL DEFAULT 0;
ALTER TABLE posts ADD COLUMN vote_count INTEGER NOT NULL DEFAULT 0;
