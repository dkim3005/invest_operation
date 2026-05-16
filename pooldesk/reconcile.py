"""Module 4 — reconciliation engine.

Reconciles the internal book of record against the custodian feed for one
business day, classifies every break, sizes its market-value impact in CAD
and writes it to ``recon_exception`` as an OPEN exception. Also runs a
per-pool cash reconciliation. See BUILD_SPEC.md Module 4.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import config
from pooldesk import db

# Severity thresholds on CAD market-value impact.
SEVERITY_HIGH_CAD = 1_000_000
SEVERITY_MEDIUM_CAD = 100_000

# Quantities below this absolute difference are treated as matched.
QTY_TOLERANCE = 0.01

_RECON_COLUMNS = [
    "break_id", "run_date", "pool_id", "security_id", "break_type",
    "internal_qty", "custodian_qty", "qty_diff", "mv_impact_cad", "severity",
    "ai_root_cause", "ai_resolution_note", "ai_owner_team", "ai_priority",
    "status",
]


def classify_severity(mv_impact_cad: float) -> str:
    """Bucket a break by its CAD market-value impact, not by row count."""
    if mv_impact_cad >= SEVERITY_HIGH_CAD:
        return "HIGH"
    if mv_impact_cad >= SEVERITY_MEDIUM_CAD:
        return "MEDIUM"
    return "LOW"


def _prior_business_day(run_date: date) -> date | None:
    days = config.business_days(config.SIM_START_DATE, config.SIM_DAYS)
    if run_date in days:
        i = days.index(run_date)
        return days[i - 1] if i > 0 else None
    return None


def _price_map(diso: str) -> dict[str, float]:
    """Per-security price for the day (mean of valid, positive prices)."""
    rows = db.query(
        "SELECT security_id, AVG(price) AS price FROM fact_price "
        "WHERE feed_date=? AND price > 0 GROUP BY security_id", (diso,))
    return dict(zip(rows.security_id, rows.price))


def _cost_basis_map(diso: str) -> dict[str, float]:
    """Fallback valuation: internal cost basis, keyed by security."""
    rows = db.query(
        "SELECT security_id, AVG(cost_basis_local) AS cost "
        "FROM fact_position_internal WHERE feed_date=? GROUP BY security_id",
        (diso,))
    return dict(zip(rows.security_id, rows.cost))


def _fx_to_cad_map(diso: str) -> dict[str, float]:
    """Currency -> rate to CAD for the day.

    If the day's USD rate is missing (an injected FX gap), the most recent
    prior rate is carried forward — matching how the feed was produced.
    """
    rows = db.query(
        "SELECT from_ccy, rate FROM fact_fx WHERE feed_date=? AND to_ccy=?",
        (diso, config.BASE_CURRENCY))
    fx = dict(zip(rows.from_ccy, rows.rate))
    fx.setdefault(config.BASE_CURRENCY, 1.0)
    if "USD" not in fx:
        prior = db.query(
            "SELECT rate FROM fact_fx WHERE feed_date < ? AND from_ccy='USD' "
            "AND to_ccy=? ORDER BY feed_date DESC LIMIT 1",
            (diso, config.BASE_CURRENCY))
        fx["USD"] = float(prior.rate.iloc[0]) if not prior.empty else 1.35
    return fx


def reconcile_positions(run_date: date) -> pd.DataFrame:
    """Internal vs custodian positions — one row per detected break."""
    diso = run_date.isoformat()
    internal = db.query(
        "SELECT pool_id, security_id, quantity AS internal_qty "
        "FROM fact_position_internal WHERE feed_date=?", (diso,))
    custodian = db.query(
        "SELECT pool_id, security_id, quantity AS custodian_qty "
        "FROM fact_position_custodian WHERE feed_date=?", (diso,))

    merged = internal.merge(custodian, on=["pool_id", "security_id"],
                            how="outer", indicator="merge_flag")

    sec_ccy = dict(db.query(
        "SELECT security_id, currency FROM dim_security").itertuples(
        index=False, name=None))
    prices = _price_map(diso)
    cost = _cost_basis_map(diso)
    fx = _fx_to_cad_map(diso)

    breaks = []
    for r in merged.itertuples(index=False):
        iqty = 0.0 if pd.isna(r.internal_qty) else float(r.internal_qty)
        cqty = 0.0 if pd.isna(r.custodian_qty) else float(r.custodian_qty)

        if r.merge_flag == "left_only":
            break_type = "MISSING_IN_CUSTODIAN"
        elif r.merge_flag == "right_only":
            break_type = "MISSING_IN_INTERNAL"
        elif abs(iqty - cqty) > QTY_TOLERANCE:
            break_type = "QUANTITY_MISMATCH"
        else:
            continue   # positions agree — no break

        qty_diff = iqty - cqty
        unit_value = prices.get(r.security_id) or cost.get(r.security_id) or 0.0
        rate = fx.get(sec_ccy.get(r.security_id, "USD"), 1.0)
        mv_impact = abs(qty_diff) * unit_value * rate
        breaks.append({
            "pool_id": r.pool_id,
            "security_id": r.security_id,
            "break_type": break_type,
            "internal_qty": round(iqty, 4),
            "custodian_qty": round(cqty, 4),
            "qty_diff": round(qty_diff, 4),
            "mv_impact_cad": round(mv_impact, 2),
            "severity": classify_severity(mv_impact),
        })
    return pd.DataFrame(breaks, columns=[
        "pool_id", "security_id", "break_type", "internal_qty",
        "custodian_qty", "qty_diff", "mv_impact_cad", "severity"])


def reconcile_cash(run_date: date) -> pd.DataFrame:
    """Per-pool cash control: ledger identity, settlement tie-out, continuity."""
    diso = run_date.isoformat()
    cash = db.query("SELECT * FROM fact_cash WHERE feed_date=?", (diso,))
    sec_ccy = dict(db.query(
        "SELECT security_id, currency FROM dim_security").itertuples(
        index=False, name=None))
    fx = _fx_to_cad_map(diso)

    # Expected trade settlement recomputed independently from SETTLED trades.
    recomputed: dict[str, float] = {}
    trades = db.query(
        "SELECT pool_id, security_id, side, quantity, price FROM fact_trade "
        "WHERE feed_date=? AND status='SETTLED'", (diso,))
    for t in trades.itertuples(index=False):
        rate = fx.get(sec_ccy.get(t.security_id, "USD"), 1.0)
        notional = t.quantity * t.price * rate
        recomputed[t.pool_id] = recomputed.get(t.pool_id, 0.0) + (
            notional if t.side == "SELL" else -notional)

    prior = _prior_business_day(run_date)
    prior_close = {}
    if prior is not None:
        prior_close = dict(db.query(
            "SELECT pool_id, closing_cash FROM fact_cash WHERE feed_date=?",
            (prior.isoformat(),)).itertuples(index=False, name=None))

    rows = []
    for r in cash.itertuples(index=False):
        identity = (r.opening_cash + r.subscriptions - r.redemptions
                    + r.trade_settlement - r.fees)
        identity_diff = identity - r.closing_cash
        settlement_diff = r.trade_settlement - recomputed.get(r.pool_id, 0.0)
        continuity_diff = (r.opening_cash - prior_close[r.pool_id]
                           if r.pool_id in prior_close else 0.0)
        ok = (abs(identity_diff) < 0.05 and abs(settlement_diff) < 1.0
              and abs(continuity_diff) < 0.05)
        rows.append({
            "pool_id": r.pool_id,
            "closing_cash": round(r.closing_cash, 2),
            "identity_diff": round(identity_diff, 4),
            "settlement_diff": round(settlement_diff, 4),
            "continuity_diff": round(continuity_diff, 4),
            "status": "OK" if ok else "BREAK",
        })
    return pd.DataFrame(rows, columns=[
        "pool_id", "closing_cash", "identity_diff", "settlement_diff",
        "continuity_diff", "status"])


def write_exceptions(run_date: date) -> int:
    """Persist position breaks to recon_exception as OPEN exceptions.

    Returns the number of breaks written.
    """
    diso = run_date.isoformat()
    breaks = reconcile_positions(run_date)
    if not breaks.empty:
        breaks = breaks.sort_values(
            ["pool_id", "security_id", "break_type"]).reset_index(drop=True)

    rows = []
    for i, b in enumerate(breaks.itertuples(index=False), start=1):
        rows.append({
            "break_id": f"BRK{run_date:%Y%m%d}{i:04d}",
            "run_date": diso,
            "pool_id": b.pool_id,
            "security_id": b.security_id,
            "break_type": b.break_type,
            "internal_qty": b.internal_qty,
            "custodian_qty": b.custodian_qty,
            "qty_diff": b.qty_diff,
            "mv_impact_cad": b.mv_impact_cad,
            "severity": b.severity,
            "ai_root_cause": None,
            "ai_resolution_note": None,
            "ai_owner_team": None,
            "ai_priority": None,
            "status": "OPEN",
        })

    df = pd.DataFrame(rows, columns=_RECON_COLUMNS)
    with db.get_connection() as conn:
        conn.execute("DELETE FROM recon_exception WHERE run_date=?", (diso,))
        db.insert_dataframe(conn, "recon_exception", df)
    return len(rows)
