-- Drop old markets table (schema is changing entirely)
DROP TABLE IF EXISTS polymarket_markets;

-- Events table
CREATE TABLE polymarket_events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    start_date TIMESTAMPTZ,
    end_date TIMESTAMPTZ,
    active BOOLEAN DEFAULT TRUE,
    liquidity NUMERIC,
    volume NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Markets table (simplified, natural key)
CREATE TABLE polymarket_markets (
    id TEXT PRIMARY KEY,
    event_id TEXT REFERENCES polymarket_events(id),
    question TEXT,
    outcomes TEXT,
    outcome_prices TEXT,
    active BOOLEAN DEFAULT TRUE,
    volume_num NUMERIC,
    liquidity_num NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_polymarket_events_active ON polymarket_events (active);
CREATE INDEX idx_polymarket_events_updated_at ON polymarket_events (updated_at);
CREATE INDEX idx_polymarket_markets_event_id ON polymarket_markets (event_id);
CREATE INDEX idx_polymarket_markets_active ON polymarket_markets (active);
CREATE INDEX idx_polymarket_markets_updated_at ON polymarket_markets (updated_at);

-- sync_runs columns already defined in 001; no alterations needed here.
