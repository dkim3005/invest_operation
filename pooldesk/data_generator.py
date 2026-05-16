"""Module 1b — daily synthetic feed generator.

Produces, for each business day, the six feed files an Investment Operations
team would receive (market prices, FX, internal positions, custodian
positions, trades, cash ledger) and deliberately injects realistic data
issues so the downstream quality and reconciliation engines have something to
find. Everything is seeded, so the same RANDOM_SEED reproduces byte-identical
files. See BUILD_SPEC.md sections 6.5 and 7.

Modelling simplifications (documented on purpose):
* The internal book of record updates from SETTLED trades only; PENDING and
  FAILED trades appear in trades.csv but do not move positions or cash.
* No external client subscriptions/redemptions are modelled — those cash
  columns are present per the schema but stay zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

import config
from pooldesk import market_data, reference

# ── Injected-issue rates (BUILD_SPEC.md section 7) ──────────────────────────
PRICE_MISSING_RATE = 0.03
PRICE_STALE_RATE = 0.05
PRICE_OUTLIER_RATE = 0.02
PRICE_DUPLICATE_RATE = 0.01
CUST_QTY_MISMATCH_RATE = 0.04
CUST_MISSING_RATE = 0.02
CUST_EXTRA_RATE = 0.01
TRADE_FAILED_RATE = 0.02
TRADE_PENDING_RATE = 0.07
STALE_PENDING_SHARE = 0.50   # share of PENDING trades that are past settlement
FX_DROP_RATE = 0.08          # chance a day's USD FX row is missing


@dataclass
class DayState:
    """Carry-forward state between business days."""
    day: date
    positions: dict[tuple[str, str], list[float]]  # (pool,sec) -> [qty, cost]
    cash: dict[str, float]                          # pool_id -> closing cash


@dataclass
class _Context:
    """Immutable inputs shared across all days of one generation run."""
    securities: pd.DataFrame
    pool_ids: list[str]
    secs_by_pool: dict[str, list[str]]
    fee_bps: dict[str, int]
    clean_prices: dict[str, dict[str, float]]   # date_iso -> {sec_id: price}
    price_panel: pd.DataFrame
    fx_panel: pd.DataFrame
    fx_dropped: dict[str, bool]                  # date_iso -> USD FX row dropped?
    effective_usd: dict[str, float]              # date_iso -> USD->CAD rate used
    rng_trade: np.random.Generator = field(repr=False)
    rng_price: np.random.Generator = field(repr=False)
    rng_cust: np.random.Generator = field(repr=False)


# ── business-day helpers ────────────────────────────────────────────────────
def _add_business_days(d: date, n: int) -> date:
    cur, added = d, 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def _sub_business_days(d: date, n: int) -> date:
    cur, removed = d, 0
    while removed < n:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            removed += 1
    return cur


def _fx_to_cad(ctx: _Context, day_iso: str, ccy: str) -> float:
    """USD/CAD for the day — the effective rate, carried forward on FX gaps.

    Using the effective rate (rather than a hidden panel rate) means every
    cash figure the generator writes is reproducible from the feed it writes.
    """
    if ccy == config.BASE_CURRENCY:
        return 1.0
    return ctx.effective_usd[day_iso]


# ── issue injection ─────────────────────────────────────────────────────────
def _pick(rng: np.random.Generator, n: int, rate: float) -> np.ndarray:
    """Pick a deterministic random subset of row indices for an issue."""
    if n == 0 or rate <= 0:
        return np.array([], dtype=int)
    k = min(n, max(1, int(round(n * rate))))
    return rng.choice(n, size=k, replace=False)


def inject_price_issues(prices: pd.DataFrame,
                        rng: np.random.Generator) -> pd.DataFrame:
    """Inject missing / stale / outlier / duplicate rows into a price feed."""
    df = prices.copy().reset_index(drop=True)
    n = len(df)

    for i in _pick(rng, n, PRICE_OUTLIER_RATE):
        base = float(df.at[i, "price"])
        if rng.random() < 0.5:                       # implausible spike
            df.at[i, "price"] = round(base * float(rng.uniform(1.3, 2.0)), 4)
        else:                                        # zero / negative price
            df.at[i, "price"] = 0.0 if rng.random() < 0.5 \
                else round(-abs(base) * 0.5, 4)

    for i in _pick(rng, n, PRICE_STALE_RATE):
        d = date.fromisoformat(df.at[i, "price_date"])
        stale = d - timedelta(days=int(rng.integers(3, 10)))
        df.at[i, "price_timestamp"] = f"{stale.isoformat()}T17:00:00"

    dups = df.loc[_pick(rng, n, PRICE_DUPLICATE_RATE)].copy()
    df = df.drop(index=_pick(rng, n, PRICE_MISSING_RATE))
    return pd.concat([df, dups], ignore_index=True)


def inject_custodian_breaks(internal: pd.DataFrame, pool_ids: list[str],
                            rng: np.random.Generator) -> pd.DataFrame:
    """Build the custodian position feed from internal positions + breaks."""
    cust = internal[["pool_id", "security_id", "quantity",
                     "position_date"]].copy().reset_index(drop=True)
    n = len(cust)

    for i in _pick(rng, n, CUST_QTY_MISMATCH_RATE):
        # Factor is kept clearly off 1.0 so every injected break is
        # unambiguously material and detectable by the reconciliation engine.
        factor = (rng.uniform(0.80, 0.95) if rng.random() < 0.5
                  else rng.uniform(1.05, 1.20))
        cust.at[i, "quantity"] = round(
            float(cust.at[i, "quantity"]) * float(factor), 2)

    cust = cust.drop(index=_pick(rng, n, CUST_MISSING_RATE)).reset_index(drop=True)

    # Extra rows: a security booked by the custodian under the wrong pool, so
    # (pool_id, security_id) has no internal counterpart.
    extra_rows = []
    for i in _pick(rng, n, CUST_EXTRA_RATE):
        src = internal.iloc[int(i)]
        others = [p for p in pool_ids if p != src["pool_id"]]
        extra_rows.append({
            "pool_id": others[int(rng.integers(0, len(others)))],
            "security_id": src["security_id"],
            "quantity": round(float(rng.integers(100, 3000)), 2),
            "position_date": src["position_date"],
        })
    if extra_rows:
        cust = pd.concat([cust, pd.DataFrame(extra_rows)], ignore_index=True)
    return cust


# ── per-day generation ──────────────────────────────────────────────────────
def _generate_trades(day: date, ctx: _Context,
                      positions: dict[tuple[str, str], list[float]]) -> pd.DataFrame:
    """0-5 trades per pool; SELL quantity is capped at the current holding."""
    rng = ctx.rng_trade
    prices = ctx.clean_prices[day.isoformat()]
    rows, seq = [], 0
    for pid in ctx.pool_ids:
        secs = ctx.secs_by_pool[pid]
        for _ in range(int(rng.integers(0, 6))):
            sid = secs[int(rng.integers(0, len(secs)))]
            mkt = prices.get(sid)
            if not mkt or mkt <= 0:
                continue
            held = positions.get((pid, sid), [0.0, 0.0])[0]
            side = "BUY" if (rng.random() < 0.55 or held <= 0) else "SELL"
            qty = float(rng.integers(100, 5000))
            if side == "SELL":
                qty = min(qty, held)
                if qty <= 0:
                    continue

            roll = rng.random()
            if roll < TRADE_FAILED_RATE:
                status = "FAILED"
            elif roll < TRADE_FAILED_RATE + TRADE_PENDING_RATE:
                status = "PENDING"
            else:
                status = "SETTLED"

            trade_date = day
            if status == "PENDING" and rng.random() < STALE_PENDING_SHARE:
                trade_date = _sub_business_days(day, int(rng.integers(3, 7)))

            seq += 1
            rows.append({
                "trade_id": f"TRD{day:%Y%m%d}{seq:03d}",
                "trade_date": trade_date.isoformat(),
                "pool_id": pid,
                "security_id": sid,
                "side": side,
                "quantity": round(qty, 2),
                "price": round(mkt * float(rng.uniform(0.99, 1.01)), 4),
                "settlement_date": _add_business_days(trade_date, 2).isoformat(),
                "status": status,
            })
    cols = ["trade_id", "trade_date", "pool_id", "security_id", "side",
            "quantity", "price", "settlement_date", "status"]
    return pd.DataFrame(rows, columns=cols)


def _apply_settled_trades(positions: dict[tuple[str, str], list[float]],
                          trades: pd.DataFrame) -> dict[tuple[str, str], list[float]]:
    """Move the internal book by SETTLED trades only (trade-date accounting)."""
    new = {k: list(v) for k, v in positions.items()}
    for t in trades.itertuples(index=False):
        if t.status != "SETTLED":
            continue
        key = (t.pool_id, t.security_id)
        qty, cost = new.get(key, [0.0, 0.0])
        if t.side == "BUY":
            total = qty + t.quantity
            cost = (qty * cost + t.quantity * t.price) / total if total else 0.0
            qty = total
        else:  # SELL — quantity already capped at the holding
            qty = max(0.0, qty - t.quantity)
        new[key] = [round(qty, 4), round(cost, 4)]
    return new


def generate_day(day: date, ctx: _Context, state: DayState) -> DayState:
    """Generate and persist one business day of feed files."""
    day_iso = day.isoformat()
    clean = ctx.clean_prices[day_iso]

    trades = _generate_trades(day, ctx, state.positions)
    positions = _apply_settled_trades(state.positions, trades)

    internal = pd.DataFrame(
        [{"pool_id": p, "security_id": s, "quantity": q,
          "cost_basis_local": c, "position_date": day_iso}
         for (p, s), (q, c) in sorted(positions.items()) if q > 0],
        columns=["pool_id", "security_id", "quantity",
                 "cost_basis_local", "position_date"])

    custodian = inject_custodian_breaks(internal, ctx.pool_ids, ctx.rng_cust)

    prices_today = ctx.price_panel[ctx.price_panel.price_date == day_iso]
    market_prices = inject_price_issues(prices_today, ctx.rng_price)

    fx_today = ctx.fx_panel[ctx.fx_panel.rate_date == day_iso].copy()
    if ctx.fx_dropped[day_iso]:                            # injected FX gap
        fx_today = fx_today[fx_today.from_ccy != "USD"]

    cash = _build_cash_ledger(day, ctx, internal, trades, clean, state.cash)

    out = config.feed_dir(day)
    out.mkdir(parents=True, exist_ok=True)
    market_prices.to_csv(out / "market_prices.csv", index=False)
    fx_today.to_csv(out / "fx_rates.csv", index=False)
    internal.to_csv(out / "internal_positions.csv", index=False)
    custodian.to_csv(out / "custodian_positions.csv", index=False)
    trades.to_csv(out / "trades.csv", index=False)
    cash.to_csv(out / "cash_ledger.csv", index=False)

    next_cash = dict(zip(cash.pool_id, cash.closing_cash))
    return DayState(day=day, positions=positions, cash=next_cash)


def _build_cash_ledger(day: date, ctx: _Context, internal: pd.DataFrame,
                       trades: pd.DataFrame, clean: dict[str, float],
                       opening: dict[str, float]) -> pd.DataFrame:
    """Per-pool cash ledger; closing satisfies the schema identity exactly."""
    day_iso = day.isoformat()
    sec_ccy = dict(zip(ctx.securities.security_id, ctx.securities.currency))
    rows = []
    for pid in ctx.pool_ids:
        # gross value (CAD) drives the daily management-fee accrual
        gross = 0.0
        for r in internal[internal.pool_id == pid].itertuples(index=False):
            px = clean.get(r.security_id, 0.0)
            gross += r.quantity * px * _fx_to_cad(ctx, day_iso,
                                                  sec_ccy.get(r.security_id, "USD"))
        # cash from SETTLED trades only
        settle = 0.0
        for t in trades[(trades.pool_id == pid)
                        & (trades.status == "SETTLED")].itertuples(index=False):
            fx = _fx_to_cad(ctx, day_iso, sec_ccy.get(t.security_id, "USD"))
            notional = t.quantity * t.price * fx
            settle += notional if t.side == "SELL" else -notional

        open_cash = opening.get(pid, round(gross * 0.03, 2))
        fees = round(gross * ctx.fee_bps[pid] / 10_000 / 365, 2)
        settle = round(settle, 2)
        closing = round(open_cash + 0.0 - 0.0 + settle - fees, 2)
        rows.append({
            "pool_id": pid, "cash_date": day_iso,
            "opening_cash": round(open_cash, 2),
            "subscriptions": 0.0, "redemptions": 0.0,
            "trade_settlement": settle, "fees": fees,
            "closing_cash": closing,
        })
    return pd.DataFrame(rows)


# ── initial state ───────────────────────────────────────────────────────────
def _initial_state(ctx: _Context, day0: date, seed: int) -> DayState:
    """Seed opening positions and cash before the first business day."""
    rng = np.random.default_rng(seed + 6)
    clean = ctx.clean_prices[day0.isoformat()]
    sec_ccy = dict(zip(ctx.securities.security_id, ctx.securities.currency))
    positions: dict[tuple[str, str], list[float]] = {}
    gross_by_pool: dict[str, float] = {p: 0.0 for p in ctx.pool_ids}

    for sec in ctx.securities.itertuples(index=False):
        px = clean.get(sec.security_id, 0.0)
        if px <= 0:
            continue
        target_notional = float(rng.uniform(2_000_000, 12_000_000))
        qty = round(target_notional / px, 2)
        positions[(sec.pool_id, sec.security_id)] = [qty, round(px, 4)]
        fx = _fx_to_cad(ctx, day0.isoformat(), sec_ccy.get(sec.security_id, "USD"))
        gross_by_pool[sec.pool_id] += qty * px * fx

    cash = {p: round(gross_by_pool[p] * 0.03, 2) for p in ctx.pool_ids}
    return DayState(day=day0 - timedelta(days=1), positions=positions, cash=cash)


# ── top-level driver ────────────────────────────────────────────────────────
def _build_context(seed: int) -> tuple[_Context, list[date]]:
    securities = pd.read_csv(config.REFERENCE_DIR / "securities_master.csv")
    pools = pd.read_csv(config.REFERENCE_DIR / "pools.csv")
    days = config.business_days(config.SIM_START_DATE, config.SIM_DAYS)

    price_panel = market_data.get_price_panel(securities, days, seed)
    fx_panel = market_data.fx_panel(days, seed)

    clean_prices: dict[str, dict[str, float]] = {}
    for row in price_panel.itertuples(index=False):
        clean_prices.setdefault(row.price_date, {})[row.security_id] = row.price

    # Decide FX-gap days up front, then resolve the effective USD/CAD rate for
    # every day — carrying the last known rate forward across a gap so the
    # cash ledger only ever uses rates reproducible from the feed itself.
    panel_usd = {r.rate_date: r.rate for r in fx_panel.itertuples(index=False)
                 if r.from_ccy == "USD"}
    rng_fx = np.random.default_rng(seed + 5)
    fx_dropped: dict[str, bool] = {}
    effective_usd: dict[str, float] = {}
    last_usd = 1.35
    for d in days:
        di = d.isoformat()
        fx_dropped[di] = bool(rng_fx.random() < FX_DROP_RATE)
        if not fx_dropped[di]:
            last_usd = panel_usd[di]
        effective_usd[di] = last_usd

    ctx = _Context(
        securities=securities,
        pool_ids=list(pools.pool_id),
        secs_by_pool={p: list(securities[securities.pool_id == p].security_id)
                      for p in pools.pool_id},
        fee_bps=dict(zip(pools.pool_id, pools.mgmt_fee_bps)),
        clean_prices=clean_prices,
        price_panel=price_panel,
        fx_panel=fx_panel,
        fx_dropped=fx_dropped,
        effective_usd=effective_usd,
        rng_trade=np.random.default_rng(seed + 2),
        rng_price=np.random.default_rng(seed + 3),
        rng_cust=np.random.default_rng(seed + 4),
    )
    return ctx, days


def generate_history(seed: int | None = None) -> None:
    """Generate the full simulation window of daily feed files."""
    seed = config.RANDOM_SEED if seed is None else seed
    config.ensure_dirs()
    ctx, days = _build_context(seed)
    state = _initial_state(ctx, days[0], seed)
    for day in days:
        state = generate_day(day, ctx, state)
    print(f"[data_generator] wrote {len(days)} business days of feeds "
          f"({days[0]} .. {days[-1]}) to {config.FEEDS_DIR}")


def generate_all(seed: int | None = None) -> None:
    """Convenience: reference data + full feed history in one call."""
    reference.write_reference_data(seed)
    generate_history(seed)
