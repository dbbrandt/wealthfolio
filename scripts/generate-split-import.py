#!/usr/bin/env python3
"""Generate an auditable, re-runnable CSV of MISSING per-account SPLIT activities.

Wealthfolio's split_price_factor correction is sourced from per-account SPLIT
activities. Any position sold before its security split never gets a SPLIT row
(the broker only reports splits for positions held through them), so its
pre-split history is valued with split-adjusted prices against un-split
quantities -> deflated. See wealthfolio/wealthfolio#1286.

This finds, per security held anywhere in the book, the splits (from Yahoo) and
emits one SPLIT row for every account that FULLY EXITED the security before the
split date (held > 0 before, held 0 on/after) and does NOT already have that
split. Accounts that held THROUGH the split are excluded: their data is already
split-consistent (broker feed or a manually-entered SPLIT), so injecting a split
would double-multiply already-post-split units. Re-running after importing
naturally drops the now-existing rows.

Read-only against the DB. Usage:
  python3 scripts/generate-split-import.py --db apps/db/app.db [--since YYYY-MM-DD] [--out FILE]
Default output: ./split-backfill-import.csv (current directory).
"""
import argparse, csv, datetime, json, sqlite3, sys, time, urllib.request

SINCE = "2021-07-01"          # WF valuation history start; earlier splits never need a factor
DEDUP_WINDOW_DAYS = 5         # treat an existing SPLIT within +/- N days as the same event

def yahoo_splits(sym):
    p1 = int(datetime.datetime(2021, 1, 1).timestamp())
    p2 = int(datetime.datetime(2027, 1, 1).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={p2}&interval=1d&events=split")
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            d = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
            out = []
            for v in (d.get("events", {}).get("splits", {}) or {}).values():
                dt = datetime.datetime.fromtimestamp(v["date"], datetime.timezone.utc).strftime("%Y-%m-%d")
                out.append((dt, v.get("numerator") or 0, v.get("denominator") or 0))
            return sorted(out)
        except Exception:
            time.sleep(1.0)
    return None  # fetch failed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="apps/db/app.db")
    ap.add_argument("--out", default="split-backfill-import.csv")
    ap.add_argument("--since", default=SINCE,
                    help="only consider splits AND holdings on/after this date (YYYY-MM-DD). "
                         "Set to your real (non-backdated) data start so positions backdated with "
                         "post-split units are skipped. Default: %(default)s")
    args = ap.parse_args()
    since = args.since

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    acct_name = {r["id"]: r["name"] for r in con.execute("SELECT id,name FROM accounts")}

    assets = con.execute(
        "SELECT DISTINCT a.id, a.instrument_symbol sym, COALESCE(a.name,a.instrument_symbol) name "
        "FROM snapshot_positions sp JOIN assets a ON a.id=sp.asset_id "
        "WHERE a.instrument_type='EQUITY' AND a.instrument_symbol IS NOT NULL"
    ).fetchall()

    rows, audit = [], {"assets": len(assets), "fetch_failed": [], "splits": 0,
                       "skipped_spinoff": 0, "deduped": 0, "post_split_only": 0}
    print(f"scanning {len(assets)} securities for splits since {since}...", file=sys.stderr)
    for a in assets:
        ys = yahoo_splits(a["sym"]); time.sleep(0.08)
        if ys is None:
            audit["fetch_failed"].append(a["sym"]); continue
        for sdate, num, den in ys:
            if sdate < since:
                continue
            # Real stock split = small-integer ratio (e.g. 2:1, 3:2, 20:1). Spinoffs come
            # through as fractional ratios with a large denominator (e.g. 1061:1000) and
            # 1:1 rows are data quirks -> exclude both; the split factor can't model them.
            ratio = (num / den) if den else 0
            if not (1 <= den <= 10 and 2 <= num <= 100 and ratio > 1):
                audit["skipped_spinoff"] += 1; continue
            audit["splits"] += 1
            # Only accounts that FULLY EXITED before the split date need a backfill.
            # A position sold before its split is valued with split-adjusted prices
            # against un-split quantities -> deflated forever (the #1286 case). But a
            # position HELD THROUGH the split is either already split-consistent (broker
            # feed / manually-entered SPLIT) or gets its own broker split, so injecting
            # one double-multiplies units that are already post-split (verified on acct
            # 1408: LRCX/ANET/COO came out 15-30x, inflating returns). So require held>0
            # in [since, sdate) AND zero holdings on/after sdate. This also excludes
            # backdated positions that persist across a later split (they show holdings
            # on/after the split date), superseding the older --since-only guard.
            held = [r["account_id"] for r in con.execute(
                "SELECT DISTINCT h.account_id FROM snapshot_positions sp "
                "JOIN holdings_snapshots h ON h.id=sp.snapshot_id "
                "WHERE sp.asset_id=? AND h.snapshot_date >= ? AND h.snapshot_date < ? AND CAST(sp.quantity AS REAL) > 0 "
                # exclude accounts that held qty>0 on/after the split date (held through, then sold later)
                "AND h.account_id NOT IN ("
                "  SELECT h2.account_id FROM snapshot_positions sp2 "
                "  JOIN holdings_snapshots h2 ON h2.id=sp2.snapshot_id "
                "  WHERE sp2.asset_id=? AND h2.snapshot_date >= ? AND CAST(sp2.quantity AS REAL) > 0) "
                # exclude accounts that STILL hold the asset at their latest snapshot. A snapshot
                # only reflects data through the last import; still holding means the position is
                # merely stale, and the broker WILL report this split on the next import (only a
                # position fully exited before the split is one the broker never reports, since it
                # has nothing left to report a split against -> that's the only case we backfill).
                # This also covers the lag case where the split date is newer than the last
                # snapshot (e.g. CRWD 2026-07-02 with 1408 snapshots ending 2026-06-25) and so
                # wouldn't otherwise show a post-split snapshot to catch it.
                "AND h.account_id NOT IN ("
                "  SELECT hs.account_id FROM snapshot_positions ps "
                "  JOIN holdings_snapshots hs ON hs.id=ps.snapshot_id "
                "  WHERE ps.asset_id=? AND CAST(ps.quantity AS REAL) > 0 "
                "    AND hs.snapshot_date=(SELECT MAX(hx.snapshot_date) FROM holdings_snapshots hx "
                "                          WHERE hx.account_id=hs.account_id))",
                (a["id"], since, sdate, a["id"], sdate, a["id"]))]
            if not held:
                audit["post_split_only"] += 1; continue
            for acct in held:
                # dedup: existing SPLIT for this account+asset within +/- window
                dup = con.execute(
                    "SELECT 1 FROM activities WHERE account_id=? AND asset_id=? AND activity_type='SPLIT' "
                    "AND ABS(julianday(substr(activity_date,1,10)) - julianday(?)) <= ? LIMIT 1",
                    (acct, a["id"], sdate, DEDUP_WINDOW_DAYS)).fetchone()
                if dup:
                    audit["deduped"] += 1; continue
                rows.append({
                    "date": datetime.datetime.strptime(sdate, "%Y-%m-%d").strftime("%m/%d/%Y"),
                    "account": acct_name.get(acct, acct),
                    "activityType": "Split",
                    "Symbol": a["sym"],
                    "Quantity": 0, "unitPrice": 0,
                    "amount": int(ratio) if float(ratio).is_integer() else ratio,
                    "Fee": 0,
                    "comment": f"{a['name']} {int(ratio) if float(ratio).is_integer() else ratio}:1 split (backfill #1286)",
                })

    rows.sort(key=lambda r: (r["Symbol"], r["date"], r["account"]))
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date","account","activityType","Symbol","Quantity","unitPrice","amount","Fee","comment"])
        w.writeheader(); w.writerows(rows)

    print(f"\n=== audit ===", file=sys.stderr)
    print(f"securities scanned      : {audit['assets']}", file=sys.stderr)
    print(f"real splits (ratio>1)   : {audit['splits']}", file=sys.stderr)
    print(f"spinoffs/quirks skipped : {audit['skipped_spinoff']}", file=sys.stderr)
    print(f"no clean pre-split exit  : {audit['post_split_only']}", file=sys.stderr)
    print(f"already-present (dedup) : {audit['deduped']}", file=sys.stderr)
    print(f"ROWS WRITTEN            : {len(rows)}  -> {args.out}", file=sys.stderr)
    if audit["fetch_failed"]:
        print(f"fetch FAILED (review)   : {', '.join(audit['fetch_failed'])}", file=sys.stderr)

if __name__ == "__main__":
    main()
