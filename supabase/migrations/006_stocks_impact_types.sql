-- Extend stocks for impact_types and enrichment progress
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS impact_types TEXT[] DEFAULT '{}';
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ready';
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS enrich_progress JSONB DEFAULT NULL;
