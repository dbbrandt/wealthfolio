# Wealthfolio Pricing Debug Guide

## How Quote Sync Works

### Sync Triggers
Quotes are synced when:
1. **App startup** - Incremental sync for all active assets
2. **Transaction changes** - After adding/editing/deleting activities
3. **Manual "Update Prices"** - User-initiated refresh
4. **"Rebuild Full History"** - Full resync from first activity date

There is **no automatic scheduled sync** - the app only fetches prices on these triggers.

### Sync Routing Logic

For **Active/RecentlyClosed** assets (incremental sync):
1. Try `get_latest_quote()` first (1 API call, real-time price)
2. If stale or fails → fall back to `get_historical_quotes()` (candles)

For **New/NeedsBackfill** assets:
- Use `get_historical_quotes()` directly (full date range)

## MarketData.app Specifics

### Endpoints Used

| Endpoint | Purpose | Price Field |
|----------|---------|-------------|
| `/stocks/quotes/{symbol}/` | Real-time quote | `last` (last traded price) |
| `/stocks/candles/D/{symbol}/` | Historical daily | `close` (daily close) |

### Known Behaviors

1. **Candles lag by 1-2 business days** - The `/candles/` endpoint never includes the current trading day

2. **Real-time supplement** - After fetching candles, the code automatically appends today's real-time quote if missing

3. **Timestamp normalization** - Real-time quotes return market close time (e.g., 8pm EDT). These are normalized to midnight Eastern to match candle format and avoid UTC date rollover issues.

## Database Queries

### Database Location

```bash
# Dev build (pnpm tauri dev or DMG with .dev identifier)
~/Library/Application Support/com.teymz.wealthfolio.dev/app.db

# Production build
~/Library/Application Support/com.teymz.wealthfolio/app.db
```

### Useful Queries

**Find asset ID for a symbol:**
```sql
SELECT id, display_code, instrument_symbol, quote_ccy 
FROM assets 
WHERE instrument_symbol = 'IDEV';
```

**Check recent quotes for an asset:**
```sql
SELECT day, close, source, timestamp 
FROM quotes 
WHERE asset_id = '<asset_id>' 
ORDER BY day DESC 
LIMIT 10;
```

**Check all quotes for a specific day:**
```sql
SELECT q.day, q.close, q.source, a.instrument_symbol
FROM quotes q
JOIN assets a ON q.asset_id = a.id
WHERE q.day = '2026-03-18'
ORDER BY a.instrument_symbol;
```

**Find quotes from a specific provider:**
```sql
SELECT day, close, asset_id 
FROM quotes 
WHERE source = 'MARKETDATA_APP' 
  AND day >= '2026-03-15'
ORDER BY day DESC;
```

**Check sync state for an asset:**
```sql
SELECT asset_id, data_source, last_synced_at, error_count, last_error
FROM quote_sync_state
WHERE asset_id = '<asset_id>';
```

**Find assets with sync errors:**
```sql
SELECT qss.asset_id, a.instrument_symbol, qss.error_count, qss.last_error
FROM quote_sync_state qss
JOIN assets a ON qss.asset_id = a.id
WHERE qss.error_count > 0;
```

## Troubleshooting

### Missing Today's Price

1. Check if the quote exists:
   ```sql
   SELECT * FROM quotes WHERE asset_id = '<id>' AND day = '2026-03-20';
   ```

2. Check sync state for errors:
   ```sql
   SELECT * FROM quote_sync_state WHERE asset_id = '<id>';
   ```

3. Verify provider priority in Settings → Market Data

### Wrong Price Stored

Compare database value with API:
```bash
# Real-time quote (what should be stored)
curl -s "https://api.marketdata.app/v1/stocks/quotes/IDEV/" \
  -H "Authorization: Token YOUR_API_KEY" | jq .

# Historical candles (for comparison)
curl -s "https://api.marketdata.app/v1/stocks/candles/D/IDEV/?from=2026-03-15&to=2026-03-20" \
  -H "Authorization: Token YOUR_API_KEY" | jq .
```

The `last` field from `/quotes/` should match the stored `close` value.

### Date Off By One Day

If a quote shows up under the wrong date (e.g., March 19 instead of March 18):
- This was a UTC timestamp rollover bug
- Fixed by normalizing timestamps to US Eastern before extracting the date
- Run "Rebuild Full History" to re-fetch with correct dates

### Provider Not Working

Check if the provider is registered:
1. Settings → Market Data → verify provider appears and has API key
2. Check logs for "API key found" or "secret store error" messages
3. On first launch, macOS may block keychain access - restart the app after granting permission

## Known Issues

### MarketData.app Real-Time Endpoint Returns Stale Prices After Market Close

**Observed**: March 20, 2026

**Symptoms**:
- Dev database shows IDEV at 81.94 for March 20
- Production shows correct close at 80.48
- All OHLC values are identical (81.94) in dev
- Pattern repeats across different securities

**Root Cause**:
The `/stocks/quotes/{symbol}/` endpoint returns stale `last` prices after market close. Testing showed:
```bash
curl "https://api.marketdata.app/v1/stocks/quotes/IDEV/"
# Returns: "last": [81.94]
# Actual close: ~80.48-80.57 (per Fidelity)
```

The sync logic (sync.rs:830) uses `fetch_latest_quote()` for Active/RecentlyClosed assets, which calls this endpoint. When it returns stale data, incorrect prices are stored.

**Why OHLC are all the same**: The real-time endpoint only returns a single `last` price. The conversion code (client.rs:446-449) copies this to open/high/low when those fields are missing:
```rust
open: market_quote.open.unwrap_or(market_quote.close),
high: market_quote.high.unwrap_or(market_quote.close),
low: market_quote.low.unwrap_or(market_quote.close),
```

**Fix Applied** (sync.rs, time_utils.rs):
Added market hours detection to prevent using real-time endpoints after market close.

- New function: `time_utils::is_market_hours()` checks if market is open based on exchange timezone and close time
- Sync logic now only uses `fetch_latest_quote()` if:
  1. Asset is Active/RecentlyClosed AND
  2. Market hours are active (weekday before close + grace period)
- After market close, automatically uses historical endpoint to get official closing prices

**Testing**:
```bash
# Before fix (after 4PM ET):
curl "https://api.marketdata.app/v1/stocks/quotes/IDEV/"
# Returns stale: "last": [81.94]

# After fix - sync.rs uses historical endpoint instead:
curl "https://api.marketdata.app/v1/stocks/candles/D/IDEV/?from=2026-03-20&to=2026-03-20"
# Returns correct close once available
```

**Note**: During market hours, real-time endpoint is still preferred for efficiency. The historical candles endpoint lags by 1-2 business days, so real-time is necessary for current-day quotes while trading.
