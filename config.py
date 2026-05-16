"""PoolDesk configuration — loads .env and exposes typed settings.

All runtime configuration flows through this module so nothing is hardcoded
elsewhere. Import it as ``import config``.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env")


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _is_placeholder(value: str) -> bool:
    """A value is unusable if it is empty or still a template placeholder."""
    return not value or "REPLACE_ME" in value.upper()


# ── Anthropic / AI ──────────────────────────────────────────
ANTHROPIC_API_KEY: str = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL: str = _get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# ── Market data ─────────────────────────────────────────────
MARKET_DATA_MODE: str = _get("MARKET_DATA_MODE", "synthetic").lower()
if MARKET_DATA_MODE not in {"synthetic", "live"}:
    MARKET_DATA_MODE = "synthetic"
ALPHAVANTAGE_API_KEY: str = _get("ALPHAVANTAGE_API_KEY")

# ── Pipeline ────────────────────────────────────────────────
BASE_CURRENCY: str = _get("BASE_CURRENCY", "CAD").upper()
RANDOM_SEED: int = int(_get("RANDOM_SEED", "42"))
SIM_DAYS: int = int(_get("SIM_DAYS", "30"))
SIM_START_DATE: date = datetime.strptime(
    _get("SIM_START_DATE", "2026-04-01"), "%Y-%m-%d"
).date()

# ── Paths (resolved relative to the project root) ───────────
DB_PATH: Path = PROJECT_ROOT / _get("DB_PATH", "pooldesk.db")
DATA_DIR: Path = PROJECT_ROOT / _get("DATA_DIR", "data")
REPORTS_DIR: Path = PROJECT_ROOT / _get("REPORTS_DIR", "reports")
REFERENCE_DIR: Path = DATA_DIR / "reference"
FEEDS_DIR: Path = DATA_DIR / "feeds"


def has_live_ai() -> bool:
    """True when a usable Anthropic API key is configured.

    When False the AI exception assistant (Module 6) uses its rule-based
    fallback, so the pipeline still runs end to end.
    """
    return not _is_placeholder(ANTHROPIC_API_KEY)


def business_days(start: date, n: int) -> list[date]:
    """Return ``n`` consecutive business days (Mon-Fri) on/after ``start``."""
    days: list[date] = []
    current = start
    while len(days) < n:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def prior_business_day(run_date: date) -> date | None:
    """The business day immediately before ``run_date`` in the sim window."""
    days = business_days(SIM_START_DATE, SIM_DAYS)
    if run_date in days:
        i = days.index(run_date)
        return days[i - 1] if i > 0 else None
    return None


def feed_dir(day: date) -> Path:
    """Directory holding the daily feed files for a given business date."""
    return FEEDS_DIR / day.strftime("%Y%m%d")


def ensure_dirs() -> None:
    """Create the runtime directory tree if it does not yet exist."""
    for d in (DATA_DIR, REFERENCE_DIR, FEEDS_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
