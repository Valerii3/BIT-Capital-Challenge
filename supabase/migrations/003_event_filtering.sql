CREATE TABLE event_filtering (
    event_id TEXT PRIMARY KEY REFERENCES polymarket_events(id) ON DELETE CASCADE,
    tag_decision TEXT NOT NULL,
    prefilter_passed BOOLEAN NOT NULL,
    relevant BOOLEAN,
    relevance_score NUMERIC,
    confidence NUMERIC,
    impact_type TEXT,
    reasoning TEXT,
    theme_labels JSONB DEFAULT '[]',
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_event_filtering_prefilter_passed ON event_filtering (prefilter_passed);
CREATE INDEX idx_event_filtering_relevant ON event_filtering (relevant);
CREATE INDEX idx_event_filtering_processed_at ON event_filtering (processed_at);
