"""Module 2 — ingestion.

Loads the reference data and the daily feed CSVs into the SQLite database.
Every load is idempotent and atomic:

* Reference tables are fully replaced inside one transaction.
* Each feed day is loaded by first reading and validating ALL six feed files,
  then DELETE-ing that ``feed_date`` and re-inserting — all in a single
  transaction that commits only on full success. A missing or malformed file
  therefore never leaves a partially refreshed business day.

See BUILD_SPEC.md Module 2.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import config
from pooldesk import db

SCHEMA_PATH = config.PROJECT_ROOT / "sql" / "schema.sql"

# reference CSV -> dimension table
_REFERENCE = [
    ("securities_master.csv",   "dim_security"),
    ("pools.csv",               "dim_pool"),
    ("clients.csv",             "dim_client"),
    ("client_allocations.csv",  "client_allocation"),
]

# feed CSV -> landing fact table
_FEEDS = [
    ("market_prices.csv",       "fact_price"),
    ("fx_rates.csv",            "fact_fx"),
    ("internal_positions.csv",  "fact_position_internal"),
    ("custodian_positions.csv", "fact_position_custodian"),
    ("trades.csv",              "fact_trade"),
    ("cash_ledger.csv",         "fact_cash"),
]


def init_db() -> None:
    """Create the schema (idempotent — uses CREATE TABLE IF NOT EXISTS)."""
    db.run_script(SCHEMA_PATH.read_text())
    print(f"[ingest] schema initialised at {config.DB_PATH}")


def _build_dim_date() -> pd.DataFrame:
    """Calendar table covering every day across the simulation window."""
    bdays = config.business_days(config.SIM_START_DATE, config.SIM_DAYS)
    rows, d = [], config.SIM_START_DATE
    while d <= bdays[-1]:
        rows.append({
            "date_id": int(d.strftime("%Y%m%d")), "date": d.isoformat(),
            "year": d.year, "month": d.month, "day": d.day,
            "is_business_day": 1 if d.weekday() < 5 else 0,
        })
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def load_reference() -> None:
    """Fully replace the dimension tables from data/reference/, atomically."""
    # Read and validate every file before touching the database.
    frames = [(table, pd.read_csv(config.REFERENCE_DIR / csv_name))
              for csv_name, table in _REFERENCE]
    frames.append(("dim_date", _build_dim_date()))

    with db.get_connection() as conn:
        for table, df in frames:
            conn.execute(f"DELETE FROM {table}")
            db.insert_dataframe(conn, table, df)
    print("[ingest] reference data loaded (securities, pools, clients, "
          "allocations, dates)")


def load_feed_day(day: date) -> int:
    """Load one business day of feed files atomically.

    Returns the number of rows loaded.
    """
    feed = config.feed_dir(day)
    if not feed.exists():
        raise FileNotFoundError(f"no feed folder for {day}: {feed}")

    # Step 1 — read and validate ALL feed files before any database write.
    frames = []
    for csv_name, table in _FEEDS:
        df = pd.read_csv(feed / csv_name)
        df.insert(0, "feed_date", day.isoformat())
        frames.append((table, df))

    # Step 2 — single transaction: delete the day, re-insert, commit once.
    total = 0
    with db.get_connection() as conn:
        for table, df in frames:
            conn.execute(f"DELETE FROM {table} WHERE feed_date = ?",
                         (day.isoformat(),))
            total += db.insert_dataframe(conn, table, df)
    return total


def load_all() -> None:
    """Initialise the schema, load reference data, then every feed day."""
    init_db()
    load_reference()
    days = config.business_days(config.SIM_START_DATE, config.SIM_DAYS)
    total = sum(load_feed_day(day) for day in days)
    print(f"[ingest] loaded {len(days)} feed days, {total} fact rows total")
