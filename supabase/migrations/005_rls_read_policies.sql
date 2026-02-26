-- Enable RLS and grant anonymous read access for the frontend.
-- The anon key can SELECT but not INSERT/UPDATE/DELETE
-- (writes go through the service-role key in API routes).

ALTER TABLE polymarket_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE polymarket_markets ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_filtering ENABLE ROW LEVEL SECURITY;
ALTER TABLE stocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_stocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_stock_mappings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_read_events" ON polymarket_events
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_read_markets" ON polymarket_markets
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_read_event_filtering" ON event_filtering
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_read_stocks" ON stocks
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_delete_stocks" ON stocks
    FOR DELETE TO anon USING (true);

CREATE POLICY "anon_read_portfolios" ON portfolios
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_read_portfolio_stocks" ON portfolio_stocks
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_read_event_stock_mappings" ON event_stock_mappings
    FOR SELECT TO anon USING (true);
