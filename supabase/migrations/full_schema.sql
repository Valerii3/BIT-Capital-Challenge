-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.event_filtering (
  event_id text NOT NULL,
  tag_decision text NOT NULL,
  prefilter_passed boolean NOT NULL,
  relevant boolean,
  relevance_score numeric,
  confidence numeric,
  impact_type text,
  reasoning text,
  theme_labels jsonb DEFAULT '[]'::jsonb,
  processed_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT event_filtering_pkey PRIMARY KEY (event_id),
  CONSTRAINT event_filtering_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.polymarket_events(id)
);
CREATE TABLE public.event_stock_mappings (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  event_id text,
  stock_id uuid,
  relevance_score numeric,
  reasoning text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  affects boolean,
  CONSTRAINT event_stock_mappings_pkey PRIMARY KEY (id),
  CONSTRAINT event_stock_mappings_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.polymarket_events(id),
  CONSTRAINT event_stock_mappings_stock_id_fkey FOREIGN KEY (stock_id) REFERENCES public.stocks(id)
);
CREATE TABLE public.polymarket_events (
  id text NOT NULL,
  title text NOT NULL,
  description text,
  start_date timestamp with time zone,
  end_date timestamp with time zone,
  active boolean DEFAULT true,
  liquidity numeric,
  volume numeric,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  tags ARRAY,
  CONSTRAINT polymarket_events_pkey PRIMARY KEY (id)
);
CREATE TABLE public.polymarket_markets (
  id text NOT NULL,
  event_id text,
  question text,
  outcomes text,
  outcome_prices text,
  active boolean DEFAULT true,
  volume_num numeric,
  liquidity_num numeric,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT polymarket_markets_pkey PRIMARY KEY (id),
  CONSTRAINT polymarket_markets_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.polymarket_events(id)
);
CREATE TABLE public.portfolio_stocks (
  portfolio_id uuid NOT NULL,
  stock_id uuid NOT NULL,
  added_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT portfolio_stocks_pkey PRIMARY KEY (portfolio_id, stock_id),
  CONSTRAINT portfolio_stocks_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id),
  CONSTRAINT portfolio_stocks_stock_id_fkey FOREIGN KEY (stock_id) REFERENCES public.stocks(id)
);
CREATE TABLE public.portfolios (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT portfolios_pkey PRIMARY KEY (id)
);
CREATE TABLE public.reports (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL,
  stock_ids ARRAY NOT NULL DEFAULT '{}'::uuid[],
  content text,
  status text NOT NULL DEFAULT 'pending'::text CHECK (status = ANY (ARRAY['pending'::text, 'generating'::text, 'ready'::text, 'failed'::text])),
  error text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  event_ids ARRAY NOT NULL,
  report_type text NOT NULL DEFAULT 'combined'::text CHECK (report_type = ANY (ARRAY['combined'::text, 'single_stock'::text, 'macro'::text, 'sector'::text])),
  progress jsonb,
  CONSTRAINT reports_pkey PRIMARY KEY (id)
);
CREATE TABLE public.stocks (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  ticker text UNIQUE,
  name text NOT NULL,
  short_description text,
  sector text,
  is_active boolean DEFAULT true,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  impact_types ARRAY DEFAULT '{}'::text[],
  status text DEFAULT 'ready'::text,
  enrich_progress jsonb,
  CONSTRAINT stocks_pkey PRIMARY KEY (id)
);
CREATE TABLE public.sync_runs (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  started_at timestamp with time zone NOT NULL DEFAULT now(),
  finished_at timestamp with time zone,
  run_status text NOT NULL DEFAULT 'running'::text,
  markets_fetched integer NOT NULL DEFAULT 0,
  markets_upserted integer NOT NULL DEFAULT 0,
  error text,
  events_upserted integer NOT NULL DEFAULT 0,
  events_fetched integer NOT NULL DEFAULT 0,
  events_deactivated integer NOT NULL DEFAULT 0,
  markets_deactivated integer NOT NULL DEFAULT 0,
  CONSTRAINT sync_runs_pkey PRIMARY KEY (id)
);