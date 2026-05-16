"""Shared pytest fixtures for the PoolDesk test suite.

Sitting at the project root, this file also puts the root on sys.path so the
tests can ``import config`` and ``from pooldesk import ...``.
"""
from __future__ import annotations

import pytest

import config
from pooldesk import data_generator, data_quality, ingest, nav, reconcile


@pytest.fixture(scope="session")
def days(tmp_path_factory) -> list:
    """Run the full pipeline once, in an isolated temporary workspace.

    Data and the SQLite database are written under a pytest temp directory and
    market data is forced to synthetic mode, so the suite never touches the
    developer's local artifacts, never hits the network, and never calls a
    live AI service. The AI triage step is intentionally skipped — the
    data-quality, reconciliation and NAV tests do not assert AI output.
    """
    tmp = tmp_path_factory.mktemp("pooldesk")
    overrides = {
        "DATA_DIR": tmp / "data",
        "REFERENCE_DIR": tmp / "data" / "reference",
        "FEEDS_DIR": tmp / "data" / "feeds",
        "REPORTS_DIR": tmp / "reports",
        "DB_PATH": tmp / "pooldesk.db",
        "MARKET_DATA_MODE": "synthetic",
    }
    saved = {key: getattr(config, key) for key in overrides}
    for key, value in overrides.items():
        setattr(config, key, value)
    try:
        data_generator.generate_all()
        ingest.load_all()
        business_days = config.business_days(config.SIM_START_DATE,
                                             config.SIM_DAYS)
        for day in business_days:
            data_quality.run_all_checks(day)
            reconcile.write_exceptions(day)
            nav.compute_nav(day)
            nav.compute_client_holdings(day)
        yield business_days
    finally:
        for key, value in saved.items():
            setattr(config, key, value)
