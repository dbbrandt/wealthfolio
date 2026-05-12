# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Commands

| Task             | Command                                                   |
| ---------------- | --------------------------------------------------------- |
| Desktop dev      | `pnpm tauri dev`                                          |
| Web dev          | `pnpm run dev:web`                                        |
| Production build | `pnpm tauri build`                                        |
| TS tests         | `pnpm test`                                               |
| Single TS test   | `pnpm --filter frontend test -- src/path/to/file.spec.ts` |
| Rust tests       | `cargo test`                                              |
| Single Rust test | `cargo test -p wealthfolio-core test_name`                |
| Type check       | `pnpm type-check`                                         |
| Lint             | `pnpm lint`                                               |
| All checks       | `pnpm check` (format + lint + type-check)                 |

Vite dev server listens on port 1420. The web Axum server defaults to 8080.

## Architecture

### Dual-Mode: Desktop vs Web

Wealthfolio runs in two modes that share all frontend code and all Rust business
logic:

- **Desktop (Tauri):** React frontend in a WebView; backend calls go via Tauri
  IPC. Runs as a native app with local SQLite.
- **Web (Axum):** React frontend served as static files; backend calls go via
  HTTP to an Axum REST server (`apps/server/`). Deployed as Docker or binary.

### Adapter System (Frontend)

The adapter system is how the frontend calls the backend without knowing which
mode it's in. At build time, Vite resolves two aliases based on `BUILD_TARGET`
env var (`tauri` or `web`):

- `@/adapters` → `apps/frontend/src/adapters/tauri/` or `.../web/`
- `#platform` → `apps/frontend/src/adapters/tauri/core.ts` or `.../web/core.ts`

**Shared adapters** live in `apps/frontend/src/adapters/shared/`. They call
`invoke(commandName, params)` imported from `#platform`. This single `invoke()`
call:

- In Tauri: calls `tauri-apps/api` IPC
- In Web: looks up `commandName` in `web/core.ts`'s `COMMANDS` map, then makes a
  `fetch()` to the matching REST endpoint

Most command logic lives in the shared adapters. Platform-specific adapters
(`tauri/` and `web/`) only implement what differs (file dialogs, event
listeners, AI streaming, addons, settings).

All imports in the frontend should use `@/adapters` — never import directly from
`tauri/` or `web/` subdirectories.

### Data Flow

```
Frontend component
  → React Query hook
    → @/adapters (shared or platform-specific)
      → invoke(commandName, params)
        ↓ Desktop                    ↓ Web
  Tauri IPC                    fetch /api/v1/...
  apps/tauri/src/commands/     apps/server/src/api/
        ↓                            ↓
              crates/core (business logic)
                      ↓
              crates/storage-sqlite (Diesel ORM)
                      ↓
                  SQLite DB
```

### Rust Crates

- **`crates/core`** — Domain entities, service traits, and all business logic.
  Database-agnostic; defines the traits that `storage-sqlite` implements.
- **`crates/storage-sqlite`** — Diesel ORM repositories. Migrations in
  `crates/storage-sqlite/migrations/`. Schema in
  `crates/storage-sqlite/src/schema.rs`.
- **`crates/market-data`** — Market data provider implementations (Yahoo,
  MarketData.app, etc.).
- **`crates/connect`** — Broker connection and sync integrations (Wealthfolio
  Connect).
- **`crates/device-sync`** — E2EE device sync engine. Uses X25519 key exchange +
  ChaCha20-Poly1305.
- **`crates/ai`** — LLM provider integrations.

### Adding a Feature (Full Stack)

1. **Core logic** → trait in `crates/core/src/<domain>/`, implementation in
   `crates/storage-sqlite/src/<domain>/`
2. **Tauri command** → `apps/tauri/src/commands/<domain>.rs`, register in
   `mod.rs` and `lib.rs`
3. **Web endpoint** → `apps/server/src/api/<domain>.rs`, call the same core
   service
4. **Web COMMANDS map** → add entry to `apps/frontend/src/adapters/web/core.ts`
5. **Shared adapter** → `apps/frontend/src/adapters/shared/<domain>.ts` using
   `invoke()`
6. **Frontend** → React Query hook → component

### UI Patterns

- Components from `@wealthfolio/ui` (resolves to `packages/ui/src/`)
- Forms: `react-hook-form` + Zod schemas from `apps/frontend/src/lib/schemas.ts`
- Theme: CSS tokens in `apps/frontend/src/globals.css`
- Routes: `apps/frontend/src/routes.tsx`

## Conventions

### TypeScript

- Strict mode; no unused locals/params
- Prefer interfaces over types; avoid enums
- Functional components, named exports
- Directory names: `lowercase-with-dashes`

### Rust

- Thin Tauri/Axum commands — delegate all logic to `crates/core`
- `Result`/`Option` with `?` propagation; `thiserror` for domain errors
- `unsafe_code` is forbidden workspace-wide

## Git

This repo is a fork of `wealthfolio/wealthfolio`.

- `origin` → `dbbrandt/wealthfolio` (fork)
- `upstream` → `wealthfolio/wealthfolio` (original)

Sync upstream: `git fetch upstream && git merge upstream/main` into `main`, then
merge `main` into feature branches.

## Local Dev Notes

- Local build is named **Wealthfolio LCB** (`com.teymz.wealthfolio.lcb`) to
  coexist with production.
- With `DATABASE_URL` set (default from `.env.sample`): database is
  `apps/db/app.db`. Without it:
  `~/Library/Application Support/com.teymz.wealthfolio.lcb/app.db`.
- Active database path visible in app: Settings → About.
- Use `.env.sample` (cloud sync disabled) for local dev, or `.env.example` with
  real Connect URLs to enable cloud sync.
- Web mode uses `../n8n` Docker Compose setup; start with
  `./scripts/start-web.sh`.
