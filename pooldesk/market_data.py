"""Module 1c — market data source abstraction.

Exposes one entry point, :func:`get_price_panel`, that returns a clean price
panel (one row per security per business day) in either of two modes:

* ``synthetic`` (default) — an offline, reproducible geometric random walk.
* ``live`` — real closing prices via yfinance, with a synthetic fallback for
  any ticker/date the download does not cover.

FX rates are always synthetic (a small random walk around USD/CAD ~1.35); a
live FX feed is out of scope and documented as a simplification.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

import config

# Per-asset-class starting-price ranges and daily volatility for the
# synthetic generator. Bonds move far less than equities/PE.
_PRICE_RANGE = {
    "EQUITY":         (40.0, 350.0),
    "FIXED_INCOME":   (85.0, 115.0),
    "PRIVATE_EQUITY": (60.0, 220.0),
    "REAL_ESTATE":    (30.0, 260.0),
    "INFRASTRUCTURE": (40.0, 130.0),
}
_DAILY_VOL = {
    "EQUITY": 0.015, "FIXED_INCOME": 0.004, "PRIVATE_EQUITY": 0.020,
    "REAL_ESTATE": 0.012, "INFRASTRUCTURE": 0.010,
}
_DRIFT = 0.0002  # small positive daily drift


def synthetic_price_panel(securities: pd.DataFrame, days: list[date],
                          seed: int) -> pd.DataFrame:
    """Geometric random walk per security — fully deterministic for a seed."""
    rng = np.random.default_rng(seed)
    rows = []
    for sec in securities.itertuples(index=False):
        lo, hi = _PRICE_RANGE.get(sec.asset_class, (50.0, 200.0))
        vol = _DAILY_VOL.get(sec.asset_class, 0.015)
        price = float(rng.uniform(lo, hi))
        for d in days:
            price *= float(np.exp(rng.normal(_DRIFT, vol)))
            rows.append({
                "security_id": sec.security_id,
                "price_date": d.isoformat(),
                "price": round(price, 4),
                "currency": sec.currency,
                "price_timestamp": f"{d.isoformat()}T17:00:00",
                "source": "SYNTH",
            })
    return pd.DataFrame(rows)


def live_price_panel(securities: pd.DataFrame, days: list[date],
                     seed: int) -> pd.DataFrame:
    """Real closing prices via yfinance, overlaid on a synthetic fallback.

    Any ticker/date yfinance does not return keeps its synthetic value, so the
    panel is always complete even if the network or a symbol fails.
    """
    panel = synthetic_price_panel(securities, days, seed)
    try:
        import yfinance as yf

        ticker_to_id = dict(zip(securities.ticker, securities.security_id))
        raw = yf.download(
            list(ticker_to_id), start=str(min(days)),
            end=str(max(days) + timedelta(days=1)),
            progress=False, group_by="column", auto_adjust=True,
        )
        if raw is None or raw.empty:
            print("[market_data] live download empty — using synthetic prices")
            return panel

        closes = raw["Close"] if "Close" in getattr(raw, "columns", []) else raw
        overrides: dict[tuple[str, str], float] = {}
        for ticker, sid in ticker_to_id.items():
            series = closes[ticker] if ticker in getattr(closes, "columns", []) \
                else (closes if closes.ndim == 1 else None)
            if series is None:
                continue
            for d in days:
                val = series.get(pd.Timestamp(d))
                if val is not None and not pd.isna(val):
                    overrides[(sid, d.isoformat())] = round(float(val), 4)

        if overrides:
            keys = list(zip(panel.security_id, panel.price_date))
            mask = pd.Series([k in overrides for k in keys], index=panel.index)
            panel.loc[mask, "price"] = [overrides[k] for k in keys
                                        if k in overrides]
            panel.loc[mask, "source"] = "YFINANCE"
            print(f"[market_data] live prices applied for {len(overrides)} "
                  f"security-days; rest synthetic")
        else:
            print("[market_data] no live prices matched — using synthetic")
    except Exception as exc:  # network / library / symbol failure
        print(f"[market_data] live mode failed ({exc}); using synthetic prices")
    return panel


def get_price_panel(securities: pd.DataFrame, days: list[date],
                    seed: int) -> pd.DataFrame:
    """Return the clean price panel for the configured market-data mode."""
    if config.MARKET_DATA_MODE == "live":
        return live_price_panel(securities, days, seed)
    return synthetic_price_panel(securities, days, seed)


def fx_panel(days: list[date], seed: int) -> pd.DataFrame:
    """USD/CAD (plus the trivial CAD/CAD) rates as a small random walk."""
    rng = np.random.default_rng(seed + 999)
    rate = 1.35
    rows = []
    for d in days:
        rate *= float(np.exp(rng.normal(0.0, 0.003)))
        rows.append({"from_ccy": "USD", "to_ccy": "CAD",
                     "rate": round(rate, 6), "rate_date": d.isoformat()})
        rows.append({"from_ccy": "CAD", "to_ccy": "CAD",
                     "rate": 1.0, "rate_date": d.isoformat()})
    return pd.DataFrame(rows)
