-- 008_reports.sql
-- Reports table: each report has a name, a set of tracked stocks, and generated content.

CREATE TABLE IF NOT EXISTS reports (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT        NOT NULL,
  stock_ids   UUID[]      NOT NULL DEFAULT '{}',
  content     TEXT,
  status      TEXT        NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reports_created_at_idx ON reports (created_at DESC);
