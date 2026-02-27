-- 012_reports_report_type_combined.sql
-- Add combined report type and make it the default.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'reports_report_type_check'
  ) THEN
    ALTER TABLE reports DROP CONSTRAINT reports_report_type_check;
  END IF;
END $$;

ALTER TABLE reports
  ADD CONSTRAINT reports_report_type_check
  CHECK (report_type IN ('combined', 'single_stock', 'macro', 'sector'));

ALTER TABLE reports
  ALTER COLUMN report_type SET DEFAULT 'combined';
