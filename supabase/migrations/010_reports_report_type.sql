-- 010_reports_report_type.sql
-- Add report type to support separate single-stock and macro report pipelines.

ALTER TABLE reports
  ADD COLUMN IF NOT EXISTS report_type TEXT NOT NULL DEFAULT 'single_stock';

UPDATE reports
SET report_type = 'single_stock'
WHERE report_type IS NULL OR report_type = '';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'reports_report_type_check'
  ) THEN
    ALTER TABLE reports
      ADD CONSTRAINT reports_report_type_check
      CHECK (report_type IN ('single_stock', 'macro'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS reports_report_type_idx ON reports (report_type);
