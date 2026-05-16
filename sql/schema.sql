-- PoolDesk — SQLite schema (Phase 2). See BUILD_SPEC.md section 8.
--
-- Implementation notes (deliberate deviations from the spec's PK sketch):
--  * Fact tables use a surrogate autoincrement `id` plus a `feed_date` tag
--    instead of a deduping composite primary key. Idempotent reloads DELETE
--    by `feed_date`. This is important because the price feed contains
--    INJECTED DUPLICATE rows — a composite PK would silently absorb them and
--    the data-quality engine could never detect them. It also handles trades
--    whose trade_date precedes the feed day they arrive in.
--  * No FOREIGN KEY constraints are declared; referential integrity is an
--    explicit data-quality check (Module 3), mirroring how a landing layer
--    accepts feeds as-is and validates afterwards.

PRAGMA foreign_keys = ON;

-- ── Dimensions ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_security (
    security_id TEXT PRIMARY KEY,
    isin        TEXT,
    ticker      TEXT,
    name        TEXT,
    asset_class TEXT,
    pool_id     TEXT,
    currency    TEXT,
    country     TEXT
);

CREATE TABLE IF NOT EXISTS dim_pool (
    pool_id        TEXT PRIMARY KEY,
    pool_name      TEXT,
    asset_class    TEXT,
    base_currency  TEXT,
    mgmt_fee_bps   INTEGER,
    inception_date TEXT
);

CREATE TABLE IF NOT EXISTS dim_client (
    client_id   TEXT PRIMARY KEY,
    client_name TEXT,
    client_type TEXT
);

-- Transfer-agency register: units each client holds in each pool.
CREATE TABLE IF NOT EXISTS client_allocation (
    client_id  TEXT,
    pool_id    TEXT,
    units_held REAL,
    as_of_date TEXT,
    PRIMARY KEY (client_id, pool_id)
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_id         INTEGER PRIMARY KEY,   -- YYYYMMDD
    date            TEXT,
    year            INTEGER,
    month           INTEGER,
    day             INTEGER,
    is_business_day INTEGER
);

-- ── Facts (landed feeds) ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_price (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_date       TEXT,
    security_id     TEXT,
    price_date      TEXT,
    price           REAL,
    currency        TEXT,
    price_timestamp TEXT,
    source          TEXT
);

CREATE TABLE IF NOT EXISTS fact_fx (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_date TEXT,
    from_ccy  TEXT,
    to_ccy    TEXT,
    rate      REAL,
    rate_date TEXT
);

CREATE TABLE IF NOT EXISTS fact_position_internal (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_date        TEXT,
    pool_id          TEXT,
    security_id      TEXT,
    quantity         REAL,
    cost_basis_local REAL,
    position_date    TEXT
);

CREATE TABLE IF NOT EXISTS fact_position_custodian (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_date     TEXT,
    pool_id       TEXT,
    security_id   TEXT,
    quantity      REAL,
    position_date TEXT
);

CREATE TABLE IF NOT EXISTS fact_trade (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_date       TEXT,
    trade_id        TEXT,
    trade_date      TEXT,
    pool_id         TEXT,
    security_id     TEXT,
    side            TEXT,
    quantity        REAL,
    price           REAL,
    settlement_date TEXT,
    status          TEXT
);

CREATE TABLE IF NOT EXISTS fact_cash (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_date        TEXT,
    pool_id          TEXT,
    cash_date        TEXT,
    opening_cash     REAL,
    subscriptions    REAL,
    redemptions      REAL,
    trade_settlement REAL,
    fees             REAL,
    closing_cash     REAL
);

-- ── Facts (computed by Module 5) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_nav (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    nav_date              TEXT,
    pool_id               TEXT,
    gross_asset_value_cad REAL,
    liabilities_cad       REAL,
    nav_cad               REAL,
    units_outstanding     REAL,
    unit_price            REAL
);

CREATE TABLE IF NOT EXISTS fact_client_holding (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    holding_date      TEXT,
    client_id         TEXT,
    pool_id           TEXT,
    units_held        REAL,
    holding_value_cad REAL
);

-- ── Operational tables ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dq_result (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date         TEXT,
    check_name       TEXT,
    severity         TEXT,
    records_checked  INTEGER,
    records_failed   INTEGER,
    pass_rate        REAL,
    detail           TEXT
);

CREATE TABLE IF NOT EXISTS recon_exception (
    break_id           TEXT PRIMARY KEY,
    run_date           TEXT,
    pool_id            TEXT,
    security_id        TEXT,
    break_type         TEXT,
    internal_qty       REAL,
    custodian_qty      REAL,
    qty_diff           REAL,
    mv_impact_cad      REAL,
    severity           TEXT,
    ai_root_cause      TEXT,
    ai_resolution_note TEXT,
    ai_owner_team      TEXT,
    ai_priority        TEXT,
    status             TEXT
);

-- ── Indexes ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_price_date     ON fact_price(price_date, security_id);
CREATE INDEX IF NOT EXISTS ix_price_feed     ON fact_price(feed_date);
CREATE INDEX IF NOT EXISTS ix_fx_date        ON fact_fx(rate_date);
CREATE INDEX IF NOT EXISTS ix_posint_key     ON fact_position_internal(position_date, pool_id, security_id);
CREATE INDEX IF NOT EXISTS ix_posint_feed    ON fact_position_internal(feed_date);
CREATE INDEX IF NOT EXISTS ix_poscust_key    ON fact_position_custodian(position_date, pool_id, security_id);
CREATE INDEX IF NOT EXISTS ix_poscust_feed   ON fact_position_custodian(feed_date);
CREATE INDEX IF NOT EXISTS ix_trade_feed     ON fact_trade(feed_date);
CREATE INDEX IF NOT EXISTS ix_trade_sec      ON fact_trade(security_id, status);
CREATE INDEX IF NOT EXISTS ix_cash_key       ON fact_cash(cash_date, pool_id);
CREATE INDEX IF NOT EXISTS ix_cash_feed      ON fact_cash(feed_date);
CREATE INDEX IF NOT EXISTS ix_nav_key        ON fact_nav(nav_date, pool_id);
CREATE INDEX IF NOT EXISTS ix_holding_key    ON fact_client_holding(holding_date, client_id, pool_id);
CREATE INDEX IF NOT EXISTS ix_dq_run         ON dq_result(run_date);
CREATE INDEX IF NOT EXISTS ix_recon_run      ON recon_exception(run_date, status);
