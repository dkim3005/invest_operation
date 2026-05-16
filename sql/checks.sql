-- PoolDesk — reconciliation & data-quality checks expressed in pure SQL.
--
-- These mirror the logic of the Python engines (reconcile.py, data_quality.py,
-- nav.py) directly in SQL, demonstrating the same operational controls with a
-- different tool. Every query is self-contained: it resolves the "as-of" day
-- from the data itself, so the file runs as-is against pooldesk.db with no
-- parameters. Run with:  sqlite3 pooldesk.db < sql/checks.sql

-- ============================================================================
-- Q1 — Position reconciliation: internal book vs custodian (latest feed day).
-- Emits quantity mismatches and one-sided positions — the same break types as
-- reconcile.py. Written with LEFT JOIN + anti-join UNION so it is portable to
-- SQLite versions without FULL OUTER JOIN.
-- ============================================================================
WITH d AS (SELECT MAX(feed_date) AS feed_date FROM fact_position_internal)
SELECT * FROM (
    SELECT i.pool_id, i.security_id,
           i.quantity AS internal_qty,
           c.quantity AS custodian_qty,
           CASE WHEN c.security_id IS NULL THEN 'MISSING_IN_CUSTODIAN'
                ELSE 'QUANTITY_MISMATCH' END AS break_type
    FROM fact_position_internal i
    LEFT JOIN fact_position_custodian c
           ON c.feed_date = i.feed_date
          AND c.pool_id = i.pool_id
          AND c.security_id = i.security_id
    WHERE i.feed_date = (SELECT feed_date FROM d)
      AND (c.security_id IS NULL OR ABS(i.quantity - c.quantity) > 0.01)
    UNION ALL
    SELECT c.pool_id, c.security_id,
           NULL AS internal_qty,
           c.quantity AS custodian_qty,
           'MISSING_IN_INTERNAL' AS break_type
    FROM fact_position_custodian c
    LEFT JOIN fact_position_internal i
           ON i.feed_date = c.feed_date
          AND i.pool_id = c.pool_id
          AND i.security_id = c.security_id
    WHERE c.feed_date = (SELECT feed_date FROM d)
      AND i.security_id IS NULL
)
ORDER BY break_type, pool_id, security_id;

-- ============================================================================
-- Q2 — Price completeness: securities held in the internal book that have no
-- price row on the latest feed day (LEFT JOIN ... IS NULL anti-join).
-- ============================================================================
WITH d AS (SELECT MAX(feed_date) AS feed_date FROM fact_position_internal)
SELECT DISTINCT i.security_id, i.pool_id
FROM fact_position_internal i
LEFT JOIN fact_price p
       ON p.feed_date = i.feed_date
      AND p.security_id = i.security_id
WHERE i.feed_date = (SELECT feed_date FROM d)
  AND p.security_id IS NULL
ORDER BY i.security_id;

-- ============================================================================
-- Q3 — Duplicate prices on the as-of feed day: (security_id, price_date) pairs
-- that appear more than once (GROUP BY ... HAVING COUNT(*) > 1). Filtered to
-- the latest feed so it matches data_quality.check_price_duplicate.
-- ============================================================================
WITH d AS (SELECT MAX(feed_date) AS feed_date FROM fact_price)
SELECT feed_date, security_id, price_date, COUNT(*) AS row_count
FROM fact_price
WHERE feed_date = (SELECT feed_date FROM d)
GROUP BY feed_date, security_id, price_date
HAVING COUNT(*) > 1
ORDER BY security_id;

-- ============================================================================
-- Q4 — Pool positions market value (CAD) on the as-of feed day:
-- SUM(quantity * price * fx-to-CAD), with book cost where the day's price is
-- missing/invalid. Prices are de-duplicated with an inner aggregate.
-- NOTE: this is a same-day valuation demonstration. It deliberately does NOT
-- replicate nav.py's cross-day price scrubbing (carry-forward of the last
-- good, non-outlier price), so it approximates rather than reproduces fact_nav.
-- ============================================================================
WITH d AS (SELECT MAX(feed_date) AS feed_date FROM fact_position_internal)
SELECT i.pool_id,
       ROUND(SUM(i.quantity * COALESCE(p.price, i.cost_basis_local) *
             CASE WHEN s.currency = 'CAD' THEN 1.0
                  ELSE COALESCE(fx.rate, 1.35) END), 2) AS positions_value_cad
FROM fact_position_internal i
JOIN dim_security s ON s.security_id = i.security_id
LEFT JOIN (SELECT feed_date, security_id, AVG(price) AS price
           FROM fact_price WHERE price > 0
           GROUP BY feed_date, security_id) p
       ON p.feed_date = i.feed_date AND p.security_id = i.security_id
LEFT JOIN fact_fx fx
       ON fx.feed_date = i.feed_date
      AND fx.from_ccy = s.currency
      AND fx.to_ccy = 'CAD'
WHERE i.feed_date = (SELECT feed_date FROM d)
GROUP BY i.pool_id
ORDER BY i.pool_id;

-- ============================================================================
-- Q5 — Unsettled-trade aging on the as-of feed day: trades the latest feed
-- still reports as PENDING past their settlement date, ranked by days overdue
-- (settlement risk). Filtered to the latest feed so historical daily snapshots
-- of the same trade are not double-counted.
-- ============================================================================
WITH d AS (SELECT MAX(feed_date) AS feed_date FROM fact_trade)
SELECT trade_id, trade_date, pool_id, security_id, side, quantity,
       settlement_date, status,
       CAST(JULIANDAY((SELECT feed_date FROM d))
            - JULIANDAY(settlement_date) AS INTEGER) AS days_overdue
FROM fact_trade
WHERE feed_date = (SELECT feed_date FROM d)
  AND status = 'PENDING'
  AND settlement_date < (SELECT feed_date FROM d)
ORDER BY days_overdue DESC;

-- ============================================================================
-- Q6 — Client concentration: rank each client's holdings within its pool by
-- CAD value, using a window function (ROW_NUMBER OVER PARTITION BY).
-- ============================================================================
WITH d AS (SELECT MAX(holding_date) AS holding_date FROM fact_client_holding)
SELECT pool_id, client_id, holding_value_cad,
       ROW_NUMBER() OVER (PARTITION BY pool_id
                          ORDER BY holding_value_cad DESC) AS rank_in_pool
FROM fact_client_holding
WHERE holding_date = (SELECT holding_date FROM d)
ORDER BY pool_id, rank_in_pool;

-- ============================================================================
-- Q7 — Break severity: classify open reconciliation breaks by CAD market-value
-- impact (CASE WHEN), alongside the stored severity for a consistency check.
-- ============================================================================
SELECT break_id, pool_id, security_id, break_type, mv_impact_cad,
       CASE WHEN mv_impact_cad >= 1000000 THEN 'HIGH'
            WHEN mv_impact_cad >=  100000 THEN 'MEDIUM'
            ELSE 'LOW' END AS computed_severity,
       severity AS stored_severity
FROM recon_exception
ORDER BY mv_impact_cad DESC;
