-- Add first_seen_at to polymarket_events.
-- The sync script sets this to run_ts on INSERT; a trigger keeps it frozen on UPDATE.

ALTER TABLE polymarket_events ADD COLUMN first_seen_at TIMESTAMPTZ;

-- Backfill existing rows with a representative timestamp from Feb 26
UPDATE polymarket_events SET first_seen_at = '2026-02-26T10:00:00+00:00';

ALTER TABLE polymarket_events ALTER COLUMN first_seen_at SET NOT NULL;

-- Freeze first_seen_at: any UPDATE must not overwrite it
CREATE OR REPLACE FUNCTION preserve_events_first_seen_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.first_seen_at = OLD.first_seen_at;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_preserve_events_first_seen_at
BEFORE UPDATE ON polymarket_events
FOR EACH ROW EXECUTE FUNCTION preserve_events_first_seen_at();
