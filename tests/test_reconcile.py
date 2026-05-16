"""Tests for Module 4 — the reconciliation engine."""
from __future__ import annotations

import pytest

from pooldesk import db, reconcile

BREAK_TYPES = {"QUANTITY_MISMATCH", "MISSING_IN_CUSTODIAN", "MISSING_IN_INTERNAL"}


# ── pure unit tests — severity boundaries ───────────────────────────────────
@pytest.mark.parametrize("mv_impact, expected", [
    (0,            "LOW"),
    (99_999.99,    "LOW"),
    (100_000,      "MEDIUM"),
    (999_999.99,   "MEDIUM"),
    (1_000_000,    "HIGH"),
    (8_500_000,    "HIGH"),
])
def test_classify_severity_boundaries(mv_impact, expected):
    assert reconcile.classify_severity(mv_impact) == expected


# ── pipeline-backed tests ───────────────────────────────────────────────────
def test_all_break_types_appear(days):
    seen: set[str] = set()
    for day in days:
        seen |= set(reconcile.reconcile_positions(day).break_type)
    assert seen == BREAK_TYPES


def test_exceptions_persisted_and_consistent(days):
    total = sum(reconcile.write_exceptions(day) for day in days)
    rows = db.query("SELECT break_id, status, mv_impact_cad, severity "
                    "FROM recon_exception")
    assert len(rows) == total
    assert rows.break_id.is_unique
    assert (rows.status == "OPEN").all()
    # stored severity must match the classifier
    for r in rows.itertuples(index=False):
        assert reconcile.classify_severity(r.mv_impact_cad) == r.severity


def test_quantity_mismatch_diff_is_signed(days):
    breaks = reconcile.reconcile_positions(days[7])
    qm = breaks[breaks.break_type == "QUANTITY_MISMATCH"]
    for r in qm.itertuples(index=False):
        assert abs(r.qty_diff - (r.internal_qty - r.custodian_qty)) < 1e-6


def test_cash_reconciliation_columns(days):
    cash = reconcile.reconcile_cash(days[10])
    assert list(cash.columns) == ["pool_id", "closing_cash", "identity_diff",
                                  "settlement_diff", "continuity_diff",
                                  "status"]
    assert cash.status.isin({"OK", "BREAK"}).all()
