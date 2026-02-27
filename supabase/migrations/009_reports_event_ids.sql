-- 009_reports_event_ids.sql
-- Track which Polymarket events were used to generate each report.

ALTER TABLE reports ADD COLUMN IF NOT EXISTS event_ids TEXT[] NOT NULL DEFAULT '{}';
