"""Module 1a — static reference data.

Builds the four reference CSVs that the rest of the pipeline treats as the
source of truth for securities, pools, clients and the transfer-agency
register. See BUILD_SPEC.md sections 6.1-6.4.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

# ── Pools — modelled on IMCO's five asset-class pools ───────────────────────
# pool_id, pool_name, asset_class, mgmt_fee_bps
POOLS: list[tuple[str, str, str, int]] = [
    ("POOL_EQ",    "Global Equity Pool",  "EQUITY",         35),
    ("POOL_FI",    "Fixed Income Pool",   "FIXED_INCOME",   20),
    ("POOL_PE",    "Private Equity Pool", "PRIVATE_EQUITY", 75),
    ("POOL_RE",    "Real Estate Pool",    "REAL_ESTATE",    55),
    ("POOL_INFRA", "Infrastructure Pool", "INFRASTRUCTURE", 50),
]
POOL_INCEPTION = "2026-01-02"

# ── Securities — real tickers mapped to IMCO's asset classes ────────────────
# NOTE: PE / Real Estate / Infrastructure pools use *listed proxies* (BDCs,
# REITs, infra holdcos). Real private assets are illiquid and valued
# periodically; they are simplified here to a daily-priced demo so the whole
# operations workflow can be simulated. See BUILD_SPEC.md section 2.4.
# ticker, name, pool_id
SECURITIES: list[tuple[str, str, str]] = [
    # Global Equity
    ("RY.TO",   "Royal Bank of Canada",          "POOL_EQ"),
    ("TD.TO",   "Toronto-Dominion Bank",         "POOL_EQ"),
    ("SHOP.TO", "Shopify Inc",                   "POOL_EQ"),
    ("CNR.TO",  "Canadian National Railway",     "POOL_EQ"),
    ("ENB.TO",  "Enbridge Inc",                  "POOL_EQ"),
    ("AAPL",    "Apple Inc",                     "POOL_EQ"),
    ("MSFT",    "Microsoft Corp",                "POOL_EQ"),
    ("NVDA",    "NVIDIA Corp",                   "POOL_EQ"),
    ("JPM",     "JPMorgan Chase & Co",           "POOL_EQ"),
    ("JNJ",     "Johnson & Johnson",             "POOL_EQ"),
    # Fixed Income (bond ETFs as proxies)
    ("AGG",     "iShares Core US Aggregate Bond","POOL_FI"),
    ("BND",     "Vanguard Total Bond Market",    "POOL_FI"),
    ("TLT",     "iShares 20+ Yr Treasury Bond",  "POOL_FI"),
    ("LQD",     "iShares iBoxx IG Corp Bond",    "POOL_FI"),
    ("IEF",     "iShares 7-10 Yr Treasury Bond", "POOL_FI"),
    ("XBB.TO",  "iShares Core CAD Universe Bond","POOL_FI"),
    ("ZAG.TO",  "BMO Aggregate Bond Index ETF",  "POOL_FI"),
    # Private Equity (listed proxies)
    ("BX",      "Blackstone Inc",                "POOL_PE"),
    ("KKR",     "KKR & Co Inc",                  "POOL_PE"),
    ("APO",     "Apollo Global Management",      "POOL_PE"),
    ("ARES",    "Ares Management Corp",          "POOL_PE"),
    ("CG",      "Carlyle Group Inc",             "POOL_PE"),
    ("BAM",     "Brookfield Asset Management",   "POOL_PE"),
    # Real Estate (listed REIT proxies)
    ("PLD",       "Prologis Inc",                "POOL_RE"),
    ("AMT",       "American Tower Corp",         "POOL_RE"),
    ("SPG",       "Simon Property Group",        "POOL_RE"),
    ("O",         "Realty Income Corp",          "POOL_RE"),
    ("REI-UN.TO", "RioCan REIT",                 "POOL_RE"),
    ("CAR-UN.TO", "Canadian Apartment REIT",     "POOL_RE"),
    # Infrastructure (listed proxies)
    ("BIP",     "Brookfield Infrastructure",     "POOL_INFRA"),
    ("AQN.TO",  "Algonquin Power & Utilities",   "POOL_INFRA"),
    ("IGF",     "iShares Global Infra ETF",      "POOL_INFRA"),
    ("NEE",     "NextEra Energy Inc",            "POOL_INFRA"),
    ("AEP",     "American Electric Power",       "POOL_INFRA"),
]

# ── Clients — FICTIONAL entities, inspired by IMCO's public-sector client mix.
# These are NOT real organisations. See BUILD_SPEC.md section 2.4.
# client_id, client_name, client_type
CLIENTS: list[tuple[str, str, str]] = [
    ("CLI01", "Ontario Public Sector Pension Fund",  "PENSION"),
    ("CLI02", "Provincial Judiciary Retirement Plan", "PENSION"),
    ("CLI03", "Workers' Insurance & Benefit Fund",    "INSURANCE"),
    ("CLI04", "Municipal Transit Employees Pension",  "PENSION"),
    ("CLI05", "Clean Water Infrastructure Reserve",   "RESERVE"),
]


def _ccy_country(ticker: str) -> tuple[str, str]:
    """Canadian (.TO) listings settle in CAD; everything else in USD."""
    if ticker.endswith(".TO"):
        return "CAD", "CA"
    return "USD", "US"


def build_securities_master() -> pd.DataFrame:
    """34-security reference table with synthetic (format-valid) ISINs."""
    rows = []
    for i, (ticker, name, pool_id) in enumerate(SECURITIES, start=1):
        currency, country = _ccy_country(ticker)
        rows.append({
            "security_id": f"SEC{i:04d}",
            "isin": f"{country}{i:010d}",   # synthetic ISIN — format only
            "ticker": ticker,
            "name": name,
            "asset_class": next(p[2] for p in POOLS if p[0] == pool_id),
            "pool_id": pool_id,
            "currency": currency,
            "country": country,
        })
    return pd.DataFrame(rows)


def build_pools() -> pd.DataFrame:
    return pd.DataFrame([
        {"pool_id": pid, "pool_name": name, "asset_class": ac,
         "base_currency": config.BASE_CURRENCY, "mgmt_fee_bps": fee,
         "inception_date": POOL_INCEPTION}
        for pid, name, ac, fee in POOLS
    ])


def build_clients() -> pd.DataFrame:
    return pd.DataFrame([
        {"client_id": cid, "client_name": name, "client_type": ctype}
        for cid, name, ctype in CLIENTS
    ])


def build_client_allocations(seed: int) -> pd.DataFrame:
    """Transfer-agency register: units each client holds in each pool.

    Every pool is guaranteed at least one client (so units_outstanding > 0),
    then each client gets a few extra randomised allocations.
    """
    rng = np.random.default_rng(seed)
    pool_ids = [p[0] for p in POOLS]
    client_ids = [c[0] for c in CLIENTS]
    pairs: set[tuple[str, str]] = set()

    # Each client anchors one pool (guarantees every pool has a client), then
    # gets 2-4 extra pools drawn from the *other* pools — so every client ends
    # up in 3-5 distinct pools, per the spec's transfer-agency rule.
    for i, cid in enumerate(client_ids):
        anchor = pool_ids[i % len(pool_ids)]
        others = [p for p in pool_ids if p != anchor]
        n_extra = int(rng.integers(2, 5))
        chosen = [anchor] + list(rng.choice(others, size=n_extra, replace=False))
        for pid in chosen:
            pairs.add((cid, str(pid)))

    rows = []
    for cid, pid in sorted(pairs):
        rows.append({
            "client_id": cid,
            "pool_id": pid,
            "units_held": float(rng.integers(50_000, 500_001)),
            "as_of_date": config.SIM_START_DATE.isoformat(),
        })
    return pd.DataFrame(rows)


def write_reference_data(seed: int | None = None) -> None:
    """Generate and persist all four reference CSVs to data/reference/."""
    seed = config.RANDOM_SEED if seed is None else seed
    config.ensure_dirs()
    build_securities_master().to_csv(
        config.REFERENCE_DIR / "securities_master.csv", index=False)
    build_pools().to_csv(
        config.REFERENCE_DIR / "pools.csv", index=False)
    build_clients().to_csv(
        config.REFERENCE_DIR / "clients.csv", index=False)
    build_client_allocations(seed).to_csv(
        config.REFERENCE_DIR / "client_allocations.csv", index=False)
    print(f"[reference] wrote 4 reference files to {config.REFERENCE_DIR}")
