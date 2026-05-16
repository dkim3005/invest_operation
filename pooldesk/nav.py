"""Module 5 — NAV, unit pricing and client allocation.

Computes each pool's net asset value, unit price and per-client holding value
for one business day, and the daily P&L. This is the financial-analysis and
transfer-agency-oversight core of the pipeline. See BUILD_SPEC.md Module 5.

NAV per pool:
    gross_asset_value = sum(quantity * price * fx_to_cad) + closing_cash
    liabilities       = management-fee accrual (prior NAV * fee_bps/1e4 / 365)
    nav               = gross_asset_value - liabilities
    unit_price        = nav / units_outstanding
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import config
from pooldesk import db
from pooldesk.data_quality import OUTLIER_MOVE_THRESHOLD
from pooldesk.reconcile import fx_to_cad_map

_NAV_COLUMNS = [
    "nav_date", "pool_id", "gross_asset_value_cad", "liabilities_cad",
    "nav_cad", "units_outstanding", "unit_price",
]
_HOLDING_COLUMNS = [
    "holding_date", "client_id", "pool_id", "units_held", "holding_value_cad",
]


def _scrubbed_prices(diso: str) -> dict[str, float]:
    """Scrubbed valuation price per security as of ``diso``.

    Walks every business day up to ``diso`` in order, carrying the last good
    price forward across days where the feed price is missing / non-positive
    or an implausible outlier (move beyond the data-quality threshold). This
    mirrors how an operations team values positions on a clean price rather
    than a raw vendor tick, and stops one bad tick cascading into later days.
    """
    rows = db.query(
        "SELECT feed_date, security_id, AVG(price) AS price FROM fact_price "
        "WHERE feed_date <= ? AND price > 0 "
        "GROUP BY feed_date, security_id ORDER BY feed_date", (diso,))
    last_good: dict[str, float] = {}
    for r in rows.itertuples(index=False):
        prev = last_good.get(r.security_id)
        if prev is None or abs(r.price / prev - 1) <= OUTLIER_MOVE_THRESHOLD:
            last_good[r.security_id] = float(r.price)
    return last_good


def compute_nav(run_date: date) -> pd.DataFrame:
    """Compute and persist per-pool NAV for one business day."""
    diso = run_date.isoformat()
    pools = db.query("SELECT pool_id, mgmt_fee_bps FROM dim_pool")
    positions = db.query(
        "SELECT pool_id, security_id, quantity, cost_basis_local "
        "FROM fact_position_internal WHERE feed_date=?", (diso,))
    sec_ccy = dict(db.query(
        "SELECT security_id, currency FROM dim_security").itertuples(
        index=False, name=None))
    fx = fx_to_cad_map(diso)
    prices = _scrubbed_prices(diso)
    cash = dict(db.query(
        "SELECT pool_id, closing_cash FROM fact_cash WHERE feed_date=?",
        (diso,)).itertuples(index=False, name=None))
    units = dict(db.query(
        "SELECT pool_id, SUM(units_held) AS u FROM client_allocation "
        "GROUP BY pool_id").itertuples(index=False, name=None))

    prior = config.prior_business_day(run_date)
    prior_nav = {}
    if prior is not None:
        prior_nav = dict(db.query(
            "SELECT pool_id, nav_cad FROM fact_nav WHERE nav_date=?",
            (prior.isoformat(),)).itertuples(index=False, name=None))

    rows = []
    for p in pools.itertuples(index=False):
        pos = positions[positions.pool_id == p.pool_id]
        gross = cash.get(p.pool_id, 0.0)
        for r in pos.itertuples(index=False):
            # Value on the scrubbed market price; fall back to book cost when
            # no market price has ever been seen (e.g. day one with a gap).
            price = prices.get(r.security_id)
            if price is None:
                price = r.cost_basis_local
            rate = fx.get(sec_ccy.get(r.security_id, "USD"), 1.0)
            gross += r.quantity * price * rate

        # Round the components first so the stored identity
        # nav = gross - liabilities holds exactly. Day one has no prior NAV —
        # fall back to the gross value as the fee base.
        gross = round(gross, 2)
        fee_base = prior_nav.get(p.pool_id, gross)
        liabilities = round(fee_base * p.mgmt_fee_bps / 10_000 / 365, 2)
        nav = round(gross - liabilities, 2)
        outstanding = units.get(p.pool_id, 0.0)
        unit_price = nav / outstanding if outstanding else 0.0
        rows.append({
            "nav_date": diso,
            "pool_id": p.pool_id,
            "gross_asset_value_cad": gross,
            "liabilities_cad": liabilities,
            "nav_cad": nav,
            "units_outstanding": round(outstanding, 4),
            "unit_price": round(unit_price, 6),
        })

    df = pd.DataFrame(rows, columns=_NAV_COLUMNS)
    with db.get_connection() as conn:
        conn.execute("DELETE FROM fact_nav WHERE nav_date=?", (diso,))
        db.insert_dataframe(conn, "fact_nav", df)
    return df


def compute_client_holdings(run_date: date) -> pd.DataFrame:
    """Value each client's units at the day's unit price (transfer agency)."""
    diso = run_date.isoformat()
    nav = db.query("SELECT pool_id, unit_price FROM fact_nav WHERE nav_date=?",
                   (diso,))
    if nav.empty:                       # NAV not computed yet for this day
        compute_nav(run_date)
        nav = db.query(
            "SELECT pool_id, unit_price FROM fact_nav WHERE nav_date=?",
            (diso,))
    unit_price = dict(nav.itertuples(index=False, name=None))

    alloc = db.query(
        "SELECT client_id, pool_id, units_held FROM client_allocation")
    rows = []
    for a in alloc.itertuples(index=False):
        price = unit_price.get(a.pool_id, 0.0)
        rows.append({
            "holding_date": diso,
            "client_id": a.client_id,
            "pool_id": a.pool_id,
            "units_held": round(a.units_held, 4),
            "holding_value_cad": round(a.units_held * price, 2),
        })

    df = pd.DataFrame(rows, columns=_HOLDING_COLUMNS)
    with db.get_connection() as conn:
        conn.execute("DELETE FROM fact_client_holding WHERE holding_date=?",
                     (diso,))
        db.insert_dataframe(conn, "fact_client_holding", df)
    return df


def daily_pnl(run_date: date) -> pd.DataFrame:
    """Per-pool day-over-day NAV change.

    Net subscriptions/redemptions are zero in this simulation, so daily P&L is
    simply nav(t) - nav(t-1).
    """
    diso = run_date.isoformat()
    today = dict(db.query(
        "SELECT pool_id, nav_cad FROM fact_nav WHERE nav_date=?",
        (diso,)).itertuples(index=False, name=None))
    prior = config.prior_business_day(run_date)
    prior_nav = {}
    if prior is not None:
        prior_nav = dict(db.query(
            "SELECT pool_id, nav_cad FROM fact_nav WHERE nav_date=?",
            (prior.isoformat(),)).itertuples(index=False, name=None))

    rows = []
    for pool_id, nav in today.items():
        base = prior_nav.get(pool_id)
        rows.append({
            "pool_id": pool_id,
            "nav_cad": round(nav, 2),
            "prior_nav_cad": round(base, 2) if base is not None else None,
            "daily_pnl_cad": round(nav - base, 2) if base is not None else 0.0,
        })
    return pd.DataFrame(rows, columns=[
        "pool_id", "nav_cad", "prior_nav_cad", "daily_pnl_cad"])
