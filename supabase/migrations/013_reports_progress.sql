-- 013_reports_progress.sql
-- Store live generation progress for UI polling.

ALTER TABLE reports
  ADD COLUMN IF NOT EXISTS progress JSONB DEFAULT NULL;
