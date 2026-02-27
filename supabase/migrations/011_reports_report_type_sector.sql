-- 011_reports_report_type_sector.sql
-- Extend report_type check to include 'sector'.

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
  CHECK (report_type IN ('single_stock', 'macro', 'sector'));
