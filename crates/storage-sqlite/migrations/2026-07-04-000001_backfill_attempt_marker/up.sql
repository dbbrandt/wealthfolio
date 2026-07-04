-- WC-40: remember the last historical-backfill attempt per asset so unfillable
-- windows (provider has no data that far back) are not refetched on every sync.
ALTER TABLE quote_sync_state ADD COLUMN backfill_attempted_at TEXT;
ALTER TABLE quote_sync_state ADD COLUMN backfill_attempted_start TEXT;
