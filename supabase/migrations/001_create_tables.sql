-- Polymarket raw market snapshots (keyed by condition_id, updated on each sync)
CREATE TABLE polymarket_markets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condition_id text NOT NULL UNIQUE,
  gamma_id text,
  question text,
  market_description text,
  outcomes text,
  outcome_prices text,
  active boolean,
  start_date_iso timestamptz,
  end_date_iso timestamptz,
  volume_num numeric,
  liquidity_num numeric,
  category text,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_polymarket_markets_active ON polymarket_markets (active);
CREATE INDEX idx_polymarket_markets_end_date_iso ON polymarket_markets (end_date_iso);
CREATE INDEX idx_polymarket_markets_volume_num ON polymarket_markets (volume_num);

-- Sync run observability
CREATE TABLE sync_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  run_status text NOT NULL DEFAULT 'running',
  markets_fetched integer NOT NULL DEFAULT 0,
  markets_upserted integer NOT NULL DEFAULT 0,
  error text
);

CREATE INDEX idx_sync_runs_started_at ON sync_runs (started_at);
CREATE INDEX idx_sync_runs_status ON sync_runs (run_status);
