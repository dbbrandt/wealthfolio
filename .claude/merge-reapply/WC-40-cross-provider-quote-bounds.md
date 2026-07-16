# WC-40 re-apply plan — cross-provider quote bounds + backfill give-up marker

Procedural companion to the `WC-40-cross-provider-quote-bounds` entry in
`.claude/upstream-merge-checklist.yaml`. The YAML entry answers "did the fix
survive the merge?" (grep manifest). This doc answers "how do I put it back when
upstream has restructured the sync code underneath it?"

Re-verify the upstream line numbers below each merge — they drift. Grep by
symbol name, not by line. Written against upstream **v3.6.2**.

## Why this fix needs a doc (most carried fixes don't)

WC-40 collides with upstream's own sync/backfill subsystem, which upstream keeps
evolving (v3.6.2 added `SyncCategory::NeedsBackfill`,
`SyncMode::BackfillHistory`, `SyncPlanningInputs`, `determine_sync_category`,
`calculate_sync_window`, and a transient `MarketDataError::ProviderExhausted`).
A plain `git` re-apply is unsafe: the trial merge of v3.6.2 auto-merged most of
our `sync.rs` and surfaced only ONE conflict — our
`record_backfill_attempt_if_needed` call sitting next to an `update_after_sync`
block that **upstream deleted**. Auto-merge silently dropping our hunks into
stale control flow is the real hazard here.

Two carried fixes are interleaved in `sync.rs` — port BOTH:

- **WC-40**: cross-provider coverage + backfill give-up marker.
- **WC-31**: `should_persist_actual_source` (preferred provider stays
  authoritative on a transient fetch fallback).

## The load-bearing decision: the trait signature change

Our WC-40 drops the `source` param from `get_quote_bounds_for_assets` so bounds
span ALL quote sources. Upstream keeps `source` and its trait doc says "only
consider quotes from the intended provider, not MANUAL or other sources." Taking
our version means editing every implementor AND caller in one build cycle — miss
one mock and the crate test binary fails to compile.

| Site        | File (v3.6.2 anchor)                                                            | Action                                                                                       |
| ----------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| trait decl  | `crates/core/src/quotes/store.rs` `fn get_quote_bounds_for_assets`              | drop `source`, use our doc comment                                                           |
| real impl   | `storage-sqlite/.../market_data/repository.rs` `fn get_quote_bounds_for_assets` | drop param; remove `AND source = ?` from SQL + its `.bind(source)`                           |
| mock impl   | `core/src/quotes/service.rs` (two impls, ~2708 & ~2822)                         | drop param                                                                                   |
| mock impl   | `core/src/quotes/service_tests.rs` (~272)                                       | drop param                                                                                   |
| call site A | `sync.rs` bulk planner (~1187)                                                  | replace `quote_bounds_by_source` grouping with one `get_quote_bounds_for_assets(&asset_ids)` |
| call site B | `sync.rs` refetch planner (~1455)                                               | replace `assets_by_provider` grouping with one call                                          |
| call site C | `sync.rs` single-asset backfill check (~1686)                                   | drop the `&state.data_source` arg                                                            |

## File-by-file port

### 1. `crates/core/src/quotes/constants.rs` — pure addition

Add `pub const BACKFILL_RETRY_INTERVAL_DAYS: i64 = 30;`.

### 2. `crates/core/src/quotes/sync_state.rs` — additive

- Add `BACKFILL_RETRY_INTERVAL_DAYS` to the `constants` import line.
- 2 fields on `QuoteSyncState`: `backfill_attempted_at: Option<DateTime<Utc>>`,
  `backfill_attempted_start: Option<NaiveDate>`.
- Init both in `QuoteSyncState::new()`.
- Methods `record_backfill_attempt(window_start)` and
  `backfill_recently_exhausted(window_start, now)`.
- The `test_backfill_recently_exhausted` unit test.

### 3. Persistence — `model.rs` + `schema.rs` + migration

- `schema.rs`: add the 2 columns at the END of **upstream's**
  `quote_sync_state!` table macro (upstream may rewrite the macro; append our
  lines, don't clobber their column set).
- `model.rs`: 2 fields on `QuoteSyncStateDB` + both `From` mappings.
  `backfill_attempted_start` uses `parse_date` (a date), NOT `parse_datetime`.
- Migration `2026-07-04-000001_backfill_attempt_marker/{up,down}.sql`: **keep
  the existing dir name.** It sorts before upstream's
  `2026-07-08_addon_storage`, but Diesel applies _pending_ migrations by version
  tracking regardless of date, so a prod DB that already ran 07-08 still picks
  it up. Renaming forces a re-run in dev DBs — don't.

### 4. `crates/core/src/quotes/sync.rs` — the manual part

- Add `should_persist_actual_source()` (WC-31) and apply it as the
  `.filter(...)` on the persist-actual-source block (where the actual provider
  used is written back to `quote_sync_state.data_source`).
- Add the `record_backfill_attempt_if_needed()` method.
- Re-place the two marker-recording calls into **upstream's restructured
  branches** (this is the conflict site). Upstream deleted the old
  `update_after_sync`-in-no-data-branch block, so find upstream's current
  success path AND its no-new-data path (grep `AssetSyncResult {`) and add the
  call to each.
- Add the two marker-gating guards: wrap upstream's
  `if start_date <= end_date {` in the bulk planner (~1228) and the refetch
  planner (~1553) with the `backfill_recently_exhausted(start_date, now)` skip +
  a `debug!` log.
- Add the 2 new fields to every `QuoteSyncState` / `QuoteSyncStateDB` literal in
  `sync.rs` tests (grep `profile_enriched_at:` to find them).

## Refinements upstream now enables (decide during port)

1. **Tighten the marker with upstream's skip reasons.** Upstream added
   `AssetSkipReason::NoDataForRange` / `NotFound` / `ProviderExhausted`. Our
   `record_backfill_attempt_if_needed` fires on any `NeedsBackfill` completion.
   You _could_ record only when the fetch returned no new early data.
   **Baseline: keep the simple unconditional-on-NeedsBackfill behavior** (it is
   correct — if earlier data existed it would have been fetched). Note the
   refinement as a follow-up, don't block the merge on it.
2. **`ProviderExhausted` is complementary, not a replacement.** It stops the
   _run_ from erroring; our marker stops _re-scheduling_ the window. Keep both.

## Risks to verify

- **MANUAL-quote interaction (new in 3.6.2).** Upstream added "MANUAL wins"
  logic in `repository.rs` (~line 130). Our all-sources bounds now count a lone
  MANUAL quote as coverage — one manual quote 5y back would suppress backfill.
  Acceptable pre-3.6.2; re-confirm it doesn't regress. If it does, the narrower
  fix is "all _provider_ sources, exclude MANUAL" (`source != 'MANUAL'`).
- **Semantic auto-merge.** Because git auto-merges most of `sync.rs`, diff the
  merged `sync.rs` against our pre-merge HEAD for the WC-40 hunks and confirm
  each landed in upstream's new control flow, not a stale location.

## Verification gate

1. `cargo build -p wealthfolio-core -p wealthfolio-storage-sqlite` — catches the
   mock-signature ripple.
2. `cargo test -p wealthfolio-core quotes::` —
   `test_backfill_recently_exhausted` and the `should_persist_actual_source`
   tests pass.
3. Migration: apply on a COPY of the prod DB (never live — standing rule),
   confirm the 2 columns exist.
4. **Runtime (the real gate):** dev-web (8088) on a prod copy, run a sync twice.
   Confirm the backfill storm is gone — look for
   `Skipping backfill for … recently attempted with no further data` and a sharp
   drop in quotes inserted per run (was ~18k rows/run, 363/439 assets). Green
   tests cannot prove this.

## Upstream contribution

Worth a PR: `ProviderExhausted` proves upstream knows the retry loop exists but
only patched the symptom (stops the run erroring, still re-schedules the
window). `upstream_status` in the YAML entry is currently `not filed`.
