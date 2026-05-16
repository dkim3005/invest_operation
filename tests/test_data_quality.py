"""Tests for Module 3 — the data quality engine."""
from __future__ import annotations

from pooldesk import data_quality
from pooldesk.data_quality import CheckResult

ALL_CHECKS = {
    "schema_validation", "price_completeness", "price_staleness",
    "price_outlier", "price_duplicate", "referential_integrity",
    "fx_completeness",
}


# ── pure unit tests ─────────────────────────────────────────────────────────
def test_pass_rate_no_records():
    """With nothing to check, the check passes (rate 1.0)."""
    assert CheckResult("c", "LOW", 0, 0, "").pass_rate == 1.0


def test_pass_rate_partial_failure():
    assert CheckResult("c", "HIGH", 200, 50, "").pass_rate == 0.75


# ── pipeline-backed tests ───────────────────────────────────────────────────
def test_all_seven_checks_run(days):
    df = data_quality.run_all_checks(days[5])
    assert len(df) == 7
    assert set(df.check_name) == ALL_CHECKS
    assert df.pass_rate.between(0.0, 1.0).all()


def test_scorecard_shape(days):
    sc = data_quality.dq_scorecard(days[5])
    assert {"run_date", "overall_score", "failed_records", "by_check"} <= set(sc)
    assert 0 <= sc["overall_score"] <= 100
    assert set(sc["by_check"]) == ALL_CHECKS


def test_injected_issues_are_detected(days):
    """The generator injects these defects, so the checks must catch them."""
    failed: dict[str, int] = {}
    for day in days:
        for r in data_quality.run_all_checks(day).itertuples(index=False):
            failed[r.check_name] = failed.get(r.check_name, 0) + r.records_failed
    for check in ("price_staleness", "price_completeness",
                  "price_outlier", "price_duplicate"):
        assert failed[check] > 0, f"{check} detected nothing"
