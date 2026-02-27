-- Add affects column: true = relevant, false = not relevant, null = not yet processed
ALTER TABLE event_stock_mappings ADD COLUMN affects BOOLEAN;

-- Backfill: existing rows are all "relevant"
UPDATE event_stock_mappings SET affects = TRUE WHERE affects IS NULL;

CREATE INDEX idx_event_stock_mappings_affects ON event_stock_mappings (stock_id, affects);
