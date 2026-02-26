-- Stocks universe
CREATE TABLE stocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker TEXT UNIQUE,
    name TEXT NOT NULL,
    short_description TEXT,
    sector TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_stocks_ticker ON stocks (ticker);
CREATE INDEX idx_stocks_is_active ON stocks (is_active);

-- Portfolios
CREATE TABLE portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Many-to-many join between portfolios and stocks
CREATE TABLE portfolio_stocks (
    portfolio_id UUID REFERENCES portfolios(id) ON DELETE CASCADE,
    stock_id UUID REFERENCES stocks(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (portfolio_id, stock_id)
);

CREATE INDEX idx_portfolio_stocks_stock_id ON portfolio_stocks (stock_id);

-- Maps a Polymarket event to a stock with relevance judgment
CREATE TABLE event_stock_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id TEXT REFERENCES polymarket_events(id) ON DELETE CASCADE,
    stock_id UUID REFERENCES stocks(id) ON DELETE CASCADE,
    relevance_score NUMERIC,
    reasoning TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, stock_id)
);

CREATE INDEX idx_event_stock_mappings_event_id ON event_stock_mappings (event_id);
CREATE INDEX idx_event_stock_mappings_stock_id ON event_stock_mappings (stock_id);
