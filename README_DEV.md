# Wealthfolio Local Development Guide

This guide covers setting up a local development environment for Wealthfolio on macOS, including building a standalone app that can coexist with the production version.

## Prerequisites

Ensure you have the following installed:

- **Node.js** (v20+): https://nodejs.org/
- **pnpm**: `npm install -g pnpm`
- **Rust**: https://www.rust-lang.org/tools/install
  ```bash
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
  source "$HOME/.cargo/env"
  ```

## Clone and Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/afadil/wealthfolio.git
   cd wealthfolio
   ```

2. **Install dependencies:**
   ```bash
   pnpm install
   ```

3. **Configure environment:**
   ```bash
   cp .env.sample .env
   ```

   The `.env.sample` file has cloud sync disabled by default for local development. If you want to enable cloud sync (Google OAuth), use:
   ```bash
   cp .env.example .env
   ```
   Then update the placeholder values with the actual Wealthfolio Connect URLs:
   ```
   CONNECT_AUTH_URL=https://auth.wealthfolio.app
   CONNECT_AUTH_PUBLISHABLE_KEY=sb_publishable_ZSZbXNtWtnh9i2nqJ2UL4A_NV8ZVutd
   CONNECT_API_URL=https://api.wealthfolio.app
   CONNECT_OAUTH_CALLBACK_URL=https://connect.wealthfolio.app/deeplink
   ```

## Configure for Local Development

To run a dev build alongside the production Wealthfolio app, you need to change the app identifier and disable code signing.

Edit `apps/tauri/tauri.conf.json`:

```json
{
  "bundle": {
    "macOS": {
      "signingIdentity": "-"   // Change from "Apple Distribution: Teymz Inc ..."
    }
  },
  "productName": "Wealthfolio Dev",      // Change from "Wealthfolio"
  "mainBinaryName": "Wealthfolio Dev",   // Change from "Wealthfolio"
  "identifier": "com.teymz.wealthfolio.dev"  // Change from "com.teymz.wealthfolio"
}
```

These changes ensure:
- The dev app has a separate identity from the production app
- Both can be installed simultaneously in `/Applications`
- Each has its own database and settings
- Code signing uses ad-hoc signing (no Apple Developer certificate required)

## Running in Development Mode

Start the development server with hot-reload:

```bash
pnpm tauri dev
```

This will:
1. Start the Vite frontend dev server at `http://localhost:1420`
2. Compile the Rust backend
3. Launch the Tauri app window

First run will take several minutes to compile the Rust code.

## Building the macOS App

Build a release version:

```bash
pnpm tauri build
```

The built app will be at:
```
target/release/bundle/macos/Wealthfolio Dev.app
```

Copy to Applications:
```bash
cp -R "target/release/bundle/macos/Wealthfolio Dev.app" /Applications/
```

The DMG is located in /Users/danielbrandt/LocalProjects/CascadeProjects/precidix/wealthfolio/target/release/bundle/dmg
It can be installed and then unmounted to do a OSX style DMG install.
```bash
cd /Users/danielbrandt/LocalProjects/CascadeProjects/precidix/wealthfolio/target/release/bundle/dmg
cp Wealthfolio\ Dev_3.1.2_aarch64.dmg ~/Downloads/
# run the dmg from the finder in downloads
hdiutil detach "/Volumes/Wealthfolio Dev"
```

**Note:** The build may show errors about DMG bundling or updater signing — these can be ignored. The `.app` bundle is still created successfully.

## First Launch: Keychain Password Prompts

On first launch after a fresh build, macOS will prompt for your password **multiple times** (typically 4 prompts) to allow Keychain access.

**Why this happens:** Wealthfolio stores secrets (sync tokens, API keys) in the macOS Keychain. With ad-hoc signing (`-`), each build has a different code signature, so macOS requires re-authorization.

**Recommended action:** Click **"Always Allow"** for each prompt. This grants permanent access to those Keychain items until the next build.

**To eliminate repeated prompts:** Create a self-signed certificate for consistent signing:

```bash
# Create a self-signed code signing certificate
# Open Keychain Access → Certificate Assistant → Create a Certificate
# - Name: "Wealthfolio Dev"
# - Certificate Type: Code Signing
# - Let me override defaults: Yes

# Then update tauri.conf.json:
# "signingIdentity": "Wealthfolio Dev"
```

## Database Location

The database path depends on whether `DATABASE_URL` is set in `.env`:

### With `DATABASE_URL` (default from `.env.sample`)

The `.env` file sets `DATABASE_URL=../db/app.db`. Since `pnpm tauri dev` runs from `apps/tauri/`, this resolves to:

```
apps/db/app.db
```

**This is the database your dev build actually uses.** Both backup and restore operations use this path when `DATABASE_URL` is set.

### Without `DATABASE_URL`

If `DATABASE_URL` is empty or unset, Tauri uses its platform app data directory:

```
~/Library/Application Support/com.teymz.wealthfolio.dev/app.db
```

### Production app (for reference)

The production Wealthfolio app always uses:

```
~/Library/Application Support/com.teymz.wealthfolio/app.db
```

### Important notes

- **Restore goes where `DATABASE_URL` points.** If you restore a backup in the dev build, it writes to `apps/db/app.db` (not the `~/Library/Application Support/` location).
- **The `com.teymz.wealthfolio.dev/app.db` file may exist but be stale** if `DATABASE_URL` is set — the app ignores it in favor of the env var path.
- To check which database your dev build is using, go to **Settings → About** in the app — it shows the active database path.

## Switching Market Data Providers (Yahoo → MarketData.app)

If your database was populated with quotes from Yahoo Finance and you want to switch US securities to use MarketData.app, you need to update two tables:

1. **`assets.provider_config`** - Controls which provider is used when fetching new quotes
2. **`quote_sync_state.data_source`** - Controls which provider's quotes are checked for existing coverage

Simply changing `quote_sync_state.data_source` alone won't work because the actual provider selection comes from `assets.provider_config.preferred_provider`.

### Check Current State

```bash
sqlite3 ~/Library/Application\ Support/com.teymz.wealthfolio.dev/app.db "
SELECT 
    a.id, 
    a.display_code,
    a.instrument_exchange_mic, 
    json_extract(a.provider_config, '$.preferred_provider') as preferred_provider,
    qss.data_source
FROM assets a
LEFT JOIN quote_sync_state qss ON qss.asset_id = a.id
WHERE a.instrument_exchange_mic IN ('XNYS', 'XNAS')
  AND a.quote_mode = 'MARKET'
LIMIT 10;
"
```

### Update US Securities to Use MarketData.app

US exchange MICs: XNYS (NYSE), XNAS (NASDAQ), ARCX (NYSE Arca), XASE (NYSE American), BATS, IEXG

```bash
sqlite3 ~/Library/Application\ Support/com.teymz.wealthfolio.dev/app.db "
-- 1. Update assets.provider_config to set preferred_provider
UPDATE assets
SET provider_config = json_set(
    COALESCE(provider_config, '{}'),
    '$.preferred_provider',
    'MARKETDATA_APP'
),
updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE instrument_exchange_mic IN ('XNYS', 'XNAS', 'ARCX', 'XASE', 'BATS', 'IEXG')
  AND quote_mode = 'MARKET'
  AND kind = 'INVESTMENT';

SELECT 'Assets updated: ' || changes();

-- 2. Update quote_sync_state to use MARKETDATA_APP
UPDATE quote_sync_state
SET data_source = 'MARKETDATA_APP',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE asset_id IN (
    SELECT id FROM assets 
    WHERE instrument_exchange_mic IN ('XNYS', 'XNAS', 'ARCX', 'XASE', 'BATS', 'IEXG')
      AND quote_mode = 'MARKET'
      AND kind = 'INVESTMENT'
);

SELECT 'Sync states updated: ' || changes();
"
```

### Rebuild Quote History

After updating the database, run **Rebuild Full History** from Settings → Market Data in the app.

The system will:
1. See no MARKETDATA_APP quotes exist (quote bounds are per-provider)
2. Treat all updated assets as "New" → fetch full history from first activity date
3. Use MarketData.app as the preferred provider

**Note:** No app restart is required. The database changes are read fresh during sync operations.

### Verify MarketData.app is Enabled

```bash
sqlite3 ~/Library/Application\ Support/com.teymz.wealthfolio.dev/app.db "
SELECT id, name, enabled, priority FROM market_data_providers WHERE id = 'MARKETDATA_APP';
"
```

Ensure `enabled = 1`. If not, enable it in Settings → Market Data → Providers.

## Architecture Overview

Wealthfolio can run in two modes:

### Desktop Mode (Tauri)
- React frontend in a native WebView
- Rust backend via Tauri IPC
- SQLite database stored locally
- No network server required

### Web Mode (Docker/Server)
- React frontend served as static files
- Rust Axum HTTP server
- Accessible from any browser
- See main README.md for Docker setup

## Troubleshooting

### Production app launches instead of dev app
Quit the production Wealthfolio app before running `pnpm tauri dev`. If using identical identifiers, macOS may launch the wrong app.

### Build fails with signing errors
Ensure `signingIdentity` is set to `"-"` for ad-hoc signing if you don't have an Apple Developer certificate.

### Cloud sync crashes the app
If using placeholder URLs in `.env`, the app will crash trying to connect. Either:
- Use `.env.sample` (cloud sync disabled)
- Use the real Wealthfolio Connect URLs shown above

### Database corruption
Delete the database and start fresh:
```bash
rm -rf ~/Library/Application\ Support/com.teymz.wealthfolio.dev/
```

## File Structure

Key files for development:

```
.env                          # Local environment config (not committed)
.env.sample                   # Template with cloud sync disabled
.env.example                  # Template with cloud sync placeholders
apps/tauri/tauri.conf.json    # Tauri/app configuration
apps/frontend/                # React frontend
crates/                       # Rust backend crates
```

## Device Sync & Connections

Wealthfolio Connect enables syncing data across multiple devices (Mac, iOS, iPad). Understanding how sync works is critical when developing locally or restoring backups.

### Sync Architecture

```
Device A (Mac)                  Server                      Device B (iOS)
─────────────────               ──────                      ──────────────
Local changes → sync_outbox → Push events → oplog → Pull events → Apply locally
                              (encrypted)          (decrypted)
```

**Key components:**
- **Oplog** — Server-side event log of all changes (with garbage collection)
- **Cursor** — Each device tracks how far it's synced (stored in `sync_cursor` table)
- **Outbox** — Local queue of changes waiting to be pushed (`sync_outbox` table)
- **LWW (Last-Write-Wins)** — Conflict resolution by timestamp

### What Gets Synced

Defined in `crates/core/src/sync/app_sync_model.rs`:
- Accounts, Activities, Assets, Quotes
- Goals, Taxonomies, Import templates
- AI threads and messages
- Holdings snapshots

### Shared vs Separate State (Critical!)

| Component | Storage | Shared Across Builds? |
|-----------|---------|----------------------|
| `device_id`, `root_key`, `key_version` | macOS Keychain (`wealthfolio_sync_identity`) | **YES** |
| `sync_cursor`, `sync_engine_state` | SQLite database | No |
| Actual data (accounts, activities) | SQLite database | No |

**The keychain is shared across ALL builds** (dev, release, debug) because the service name `wealthfolio_sync_identity` has no app identifier prefix. This means:
- All builds claim to be the same device to the server
- But each build may have different data and cursors
- This can cause sync to appear "up to date" when data actually differs

### Diagnosing Sync Issues

**Check outbox status (sending device):**
```bash
sqlite3 apps/db/app.db "SELECT COUNT(*), status FROM sync_outbox GROUP BY status;"
```
- `pending` = waiting to push
- `sent` = successfully pushed  
- `dead` = permanently failed (key version mismatch, etc.)

**Check engine status:**
```bash
sqlite3 apps/db/app.db "SELECT * FROM sync_engine_state;"
sqlite3 apps/db/app.db "SELECT * FROM sync_cursor;"
```

### Restoring from Backup — Sync Implications

When you restore a backup, the local cursor goes backwards but the server's oplog doesn't:

```
Server oplog: [event_1 ... event_200]  cursor=200
Your restore: cursor=50, old data

Result: Sync tries to pull events 51-200, potentially:
- Recreating deleted entities
- Overwriting your restored data
- Failing due to missing references
```

**To make a restored device the source of truth:**
1. Go to Settings → Connected Devices
2. Click "Force Sync from This Device" (dev builds)
3. This calls `reinitializeSync()` which:
   - Resets server oplog
   - Bumps key version (invalidates other devices)
   - Uploads snapshot from your current data
   - Other devices must reconnect

### Sync States

| State | Meaning |
|-------|----------|
| `FRESH` | Never enrolled on this device |
| `REGISTERED` | Enrolled but needs pairing (no E2EE keys) |
| `READY` | Fully operational |
| `STALE` | Local key version < server key version |
| `RECOVERY` | Device ID not found/revoked on server |
| `ORPHANED` | Keys exist on server but no trusted devices |

### Engine Cycle Statuses

| Status | Meaning |
|--------|----------|
| `ok` | Sync completed successfully |
| `stale_cursor` | Local cursor too old, needs bootstrap snapshot |
| `wait_snapshot` | Needs snapshot but none available yet |
| `not_ready` | Device not in READY state |
| `preempted` | Another sync cycle took over |

---

## Holdings-Based Accounts

Wealthfolio supports two types of accounts:

### Activity-Based Accounts (Default)
- Positions computed from buy/sell/dividend transactions in `activities` table
- Account-asset relationship stored via `account_id` + `asset_id` columns in activities
- Asset's `is_active` flag computed from activity presence
- Quote syncing works automatically for active assets

### Holdings-Based Accounts (e.g., TIAA)
- No activities — positions stored as JSON snapshots in `holdings_snapshots` table
- Account-asset relationship embedded in `positions` JSON field (HashMap of asset_id → position)
- Typically created via external import or brokerage connection that only provides point-in-time holdings

**Known limitation:** The `is_active` flag on `assets` is computed from the `activities` table. Assets that only appear in holdings snapshots get marked `is_active = 0`, which excludes them from automatic quote syncing.

**Current workaround:**
```bash
# 1. Mark holdings-based assets as active
sqlite3 ~/Library/Application\ Support/com.teymz.wealthfolio.dev/app.db "
UPDATE assets SET is_active = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE id IN (
    SELECT DISTINCT json_each.key as asset_id
    FROM holdings_snapshots, json_each(holdings_snapshots.positions)
    where holdings_snapshots.account_id = 'a0f9246f-77b5-4248-9bd6-e5d8e642aa04'
);"

# 2. Ensure quote_sync_state entries exist (quote sync creates these on first run)
# Run a quote sync from the app after step 1
```

**Schema reference:**
```sql
holdings_snapshots:
  id, account_id, snapshot_date, positions (JSON), created_at, updated_at

positions JSON structure:
{
  "<asset_id>": {
    "accountId": "...",
    "assetId": "...",
    "quantity": 14.73,
    "averageCost": 483.87,
    "totalCostBasis": 7128.94,
    "currency": "USD",
    ...
  }
}
```

---

## Recent Feature Changes

### Account Group Performance Tracking

Added support for viewing performance metrics at the Account Group level (in addition to individual accounts and total portfolio).

**Key changes:**
- `PerformanceService` (`crates/core/src/portfolio/performance/performance_service.rs`) — added `account_group` support with aggregated valuations across grouped accounts
- `TrackedItem` type — extended to include `account_group` variant
- Account selector components — added GROUPS section to both desktop (`account-selector.tsx`) and mobile (`account-selector-mobile.tsx`) selectors
- Performance page — wired up group selection

**Architecture:**
When an account group is selected, the service aggregates daily valuations from all accounts in that group, then runs the same TWR/MWR calculations used for individual accounts.

**Planned extensions:**
- TBD

---

## Running Tests

```bash
# TypeScript tests
pnpm test

# Rust tests
cargo test

# Type checking
pnpm type-check

# Linting
pnpm lint
```
