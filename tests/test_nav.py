"""Tests for Module 5 — NAV, unit pricing and client allocation."""
from __future__ import annotations

from pooldesk import db, nav


def test_nav_and_unit_price_positive(days):
    rows = db.query("SELECT nav_cad, unit_price, units_outstanding "
                    "FROM fact_nav")
    assert (rows.nav_cad > 0).all()
    assert (rows.unit_price > 0).all()
    assert (rows.units_outstanding > 0).all()


def test_client_holdings_reconcile_to_nav(days):
    """Sum of client holding values must equal each pool's NAV."""
    chk = db.query("""
        SELECT n.nav_cad,
               (SELECT COALESCE(SUM(h.holding_value_cad), 0)
                  FROM fact_client_holding h
                 WHERE h.holding_date = n.nav_date
                   AND h.pool_id = n.pool_id) AS sum_holdings
        FROM fact_nav n""")
    rel_err = ((chk.nav_cad - chk.sum_holdings).abs() / chk.nav_cad)
    assert rel_err.max() < 1e-4


def test_nav_identity_holds(days):
    """nav = gross asset value - liabilities, per stored row."""
    rows = db.query("SELECT gross_asset_value_cad, liabilities_cad, nav_cad "
                     "FROM fact_nav")
    for r in rows.itertuples(index=False):
        assert abs((r.gross_asset_value_cad - r.liabilities_cad)
                   - r.nav_cad) < 0.01


def test_daily_pnl_shape(days):
    pnl = nav.daily_pnl(days[10])
    assert list(pnl.columns) == ["pool_id", "nav_cad", "prior_nav_cad",
                                 "daily_pnl_cad"]
    assert len(pnl) == 5                       # one row per pool
