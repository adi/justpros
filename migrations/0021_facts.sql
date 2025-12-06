-- Facts system: professional facts about users and pages
CREATE TABLE facts (
    id SERIAL PRIMARY KEY,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    subject_page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    template_id VARCHAR(50),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    public_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '72 hours',
    vetoed_at TIMESTAMPTZ,
    vote_sum INTEGER NOT NULL DEFAULT 0,
    vote_count INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT facts_one_subject CHECK (
        (subject_user_id IS NOT NULL AND subject_page_id IS NULL) OR
        (subject_user_id IS NULL AND subject_page_id IS NOT NULL)
    ),
    CONSTRAINT facts_not_self CHECK (author_id != subject_user_id)
);

CREATE INDEX idx_facts_author ON facts(author_id);
CREATE INDEX idx_facts_subject_user ON facts(subject_user_id) WHERE subject_user_id IS NOT NULL;
CREATE INDEX idx_facts_subject_page ON facts(subject_page_id) WHERE subject_page_id IS NOT NULL;
CREATE INDEX idx_facts_public ON facts(public_at) WHERE vetoed_at IS NULL;

CREATE TABLE fact_votes (
    fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    value SMALLINT NOT NULL CHECK (value >= -3 AND value <= 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (fact_id, user_id)
);

CREATE INDEX idx_fact_votes_user ON fact_votes(user_id);
