"""Module 3 — data quality engine.

Runs seven independent checks over one business day of landed feed data,
persists each result to ``dq_result`` and produces a 0-100 scorecard. The
checks are designed to catch the issues the data generator deliberately
injects (missing / stale / outlier / duplicate prices, FX gaps). See
BUILD_SPEC.md Module 3.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import config
from pooldesk import db

# Required non-null columns per landed feed table (schema validation).
_REQUIRED_COLUMNS = {
    "fact_price":              ["security_id", "price"],
    "fact_trade":              ["trade_id", "security_id", "quantity",
                                "price", "status"],
    "fact_position_internal":  ["pool_id", "security_id", "quantity"],
    "fact_position_custodian": ["pool_id", "security_id", "quantity"],
    "fact_fx":                 ["from_ccy", "to_ccy", "rate"],
    "fact_cash":               ["pool_id", "closing_cash"],
}

# How far a daily price may move before it is treated as an outlier.
OUTLIER_MOVE_THRESHOLD = 0.25


@dataclass
class CheckResult:
    """Outcome of one data-quality check for one business day."""
    check_name: str
    severity: str           # HIGH / MEDIUM / LOW
    records_checked: int
    records_failed: int
    detail: str

    @property
    def pass_rate(self) -> float:
        if self.records_checked == 0:
            return 1.0
        return 1.0 - self.records_failed / self.records_checked


def _scalar(sql: str, params: tuple) -> int:
    """Run a COUNT-style query and return the single integer result."""
    return int(db.query(sql, params).iloc[0, 0])


def _prior_business_day(run_date: date) -> date | None:
    """The business day immediately before run_date within the sim window."""
    days = config.business_days(config.SIM_START_DATE, config.SIM_DAYS)
    if run_date in days:
        i = days.index(run_date)
        return days[i - 1] if i > 0 else None
    return None


# ── individual checks ───────────────────────────────────────────────────────
def check_schema_validation(run_date: date) -> CheckResult:
    """Required columns must be present and non-null on every landed row."""
    diso = run_date.isoformat()
    checked = failed = 0
    details = []
    for table, cols in _REQUIRED_COLUMNS.items():
        n = _scalar(f"SELECT COUNT(*) FROM {table} WHERE feed_date=?", (diso,))
        cond = " OR ".join(f"{c} IS NULL" for c in cols)
        bad = _scalar(f"SELECT COUNT(*) FROM {table} "
                      f"WHERE feed_date=? AND ({cond})", (diso,))
        checked += n
        failed += bad
        if bad:
            details.append(f"{table}: {bad} rows with null required fields")
    return CheckResult("schema_validation", "HIGH", checked, failed,
                       "; ".join(details) or "all required fields present")


def check_price_completeness(run_date: date) -> CheckResult:
    """Every security held in the internal book needs a price for the day."""
    diso = run_date.isoformat()
    held = set(db.query(
        "SELECT DISTINCT security_id FROM fact_position_internal "
        "WHERE feed_date=?", (diso,)).security_id)
    priced = set(db.query(
        "SELECT DISTINCT security_id FROM fact_price WHERE feed_date=?",
        (diso,)).security_id)
    missing = sorted(held - priced)
    detail = ("all held securities priced" if not missing
              else f"{len(missing)} held securities without a price: "
                   f"{', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}")
    return CheckResult("price_completeness", "HIGH", len(held), len(missing),
                       detail)


def check_price_staleness(run_date: date) -> CheckResult:
    """A price not refreshed for the business day being validated is stale.

    Staleness is measured against ``run_date`` itself (not the row's own
    price_date), so a row carrying both an old price_date and an old
    timestamp is still caught.
    """
    diso = run_date.isoformat()
    checked = _scalar("SELECT COUNT(*) FROM fact_price WHERE feed_date=?",
                      (diso,))
    failed = _scalar(
        "SELECT COUNT(*) FROM fact_price "
        "WHERE feed_date=? AND substr(price_timestamp,1,10) < ?",
        (diso, diso))
    return CheckResult("price_staleness", "MEDIUM", checked, failed,
                       f"{failed} stale prices (timestamp precedes {diso})")


def check_price_outlier(run_date: date) -> CheckResult:
    """Non-positive prices, or moves beyond +/-25% versus the prior day."""
    diso = run_date.isoformat()
    today = db.query(
        "SELECT security_id, price FROM fact_price WHERE feed_date=?", (diso,))
    prior_day = _prior_business_day(run_date)
    prior = {}
    if prior_day is not None:
        for r in db.query(
                "SELECT security_id, price FROM fact_price WHERE feed_date=?",
                (prior_day.isoformat(),)).itertuples(index=False):
            prior[r.security_id] = r.price

    nonpositive = moved = 0
    for r in today.itertuples(index=False):
        if r.price is None or r.price <= 0:
            nonpositive += 1
            continue
        base = prior.get(r.security_id)
        if base and base > 0 and abs(r.price / base - 1) > OUTLIER_MOVE_THRESHOLD:
            moved += 1
    failed = nonpositive + moved
    return CheckResult("price_outlier", "HIGH", len(today), failed,
                       f"{nonpositive} non-positive, {moved} moved > "
                       f"{OUTLIER_MOVE_THRESHOLD:.0%} vs prior day")


def check_price_duplicate(run_date: date) -> CheckResult:
    """A (security_id, price_date) pair must appear at most once."""
    diso = run_date.isoformat()
    total = _scalar("SELECT COUNT(*) FROM fact_price WHERE feed_date=?",
                    (diso,))
    distinct = _scalar(
        "SELECT COUNT(*) FROM (SELECT 1 FROM fact_price WHERE feed_date=? "
        "GROUP BY security_id, price_date)", (diso,))
    failed = total - distinct
    return CheckResult("price_duplicate", "MEDIUM", total, failed,
                       f"{failed} duplicate price rows")


def check_referential_integrity(run_date: date) -> CheckResult:
    """Position security_id / pool_id must exist in the master tables."""
    diso = run_date.isoformat()
    checked = failed = 0
    for table in ("fact_position_internal", "fact_position_custodian"):
        checked += _scalar(f"SELECT COUNT(*) FROM {table} WHERE feed_date=?",
                            (diso,))
        failed += _scalar(
            f"SELECT COUNT(*) FROM {table} WHERE feed_date=? AND ("
            "security_id NOT IN (SELECT security_id FROM dim_security) OR "
            "pool_id NOT IN (SELECT pool_id FROM dim_pool))", (diso,))
    return CheckResult("referential_integrity", "HIGH", checked, failed,
                       f"{failed} position rows reference unknown "
                       f"security/pool")


def check_fx_completeness(run_date: date) -> CheckResult:
    """Every non-base currency held must have an FX rate for the day."""
    diso = run_date.isoformat()
    needed = set(db.query(
        "SELECT DISTINCT s.currency FROM fact_position_internal p "
        "JOIN dim_security s ON s.security_id = p.security_id "
        "WHERE p.feed_date=? AND s.currency <> ?",
        (diso, config.BASE_CURRENCY)).currency)
    have = set(db.query(
        "SELECT DISTINCT from_ccy FROM fact_fx WHERE feed_date=?",
        (diso,)).from_ccy)
    missing = sorted(needed - have)
    detail = ("all required FX rates present" if not missing
              else f"missing FX rate(s): {', '.join(missing)}")
    return CheckResult("fx_completeness", "MEDIUM", len(needed), len(missing),
                       detail)


_CHECKS = (
    check_schema_validation,
    check_price_completeness,
    check_price_staleness,
    check_price_outlier,
    check_price_duplicate,
    check_referential_integrity,
    check_fx_completeness,
)


# ── orchestration ───────────────────────────────────────────────────────────
def run_all_checks(run_date: date):
    """Run all seven checks for a day and persist them to dq_result.

    Returns the results as a DataFrame.
    """
    import pandas as pd

    results = [check(run_date) for check in _CHECKS]
    df = pd.DataFrame([{
        "run_date": run_date.isoformat(),
        "check_name": r.check_name,
        "severity": r.severity,
        "records_checked": r.records_checked,
        "records_failed": r.records_failed,
        "pass_rate": round(r.pass_rate, 4),
        "detail": r.detail,
    } for r in results])

    with db.get_connection() as conn:
        conn.execute("DELETE FROM dq_result WHERE run_date=?",
                     (run_date.isoformat(),))
        db.insert_dataframe(conn, "dq_result", df)
    return df


def dq_scorecard(run_date: date) -> dict:
    """Summarise a day's checks as an overall 0-100 score plus a breakdown.

    Runs the checks first if they have not been persisted yet.
    """
    diso = run_date.isoformat()
    rows = db.query("SELECT * FROM dq_result WHERE run_date=?", (diso,))
    if rows.empty:
        run_all_checks(run_date)
        rows = db.query("SELECT * FROM dq_result WHERE run_date=?", (diso,))

    by_check = {
        r.check_name: {
            "severity": r.severity,
            "pass_rate": float(r.pass_rate),
            "records_checked": int(r.records_checked),
            "records_failed": int(r.records_failed),
        }
        for r in rows.itertuples(index=False)
    }
    overall = round(float(rows.pass_rate.mean()) * 100, 1) if not rows.empty else 0.0
    return {
        "run_date": diso,
        "overall_score": overall,
        "failed_records": int(rows.records_failed.sum()),
        "by_check": by_check,
    }
