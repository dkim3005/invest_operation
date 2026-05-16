"""Module 6 — AI exception assistant.

For each OPEN reconciliation break, classifies the probable root cause,
assigns an owner team and priority, and drafts a short resolution note.

Two execution paths, same output schema:

* LLM path (when a real ANTHROPIC_API_KEY is configured) — one batched
  Claude call per day using structured outputs and a cached system prompt.
* Rule-based fallback (no key, or any API failure) — a deterministic
  classifier so the pipeline always runs end to end.

The assistant only *triages* — breaks stay OPEN. Resolution is a human
decision (human-in-the-loop). See BUILD_SPEC.md Module 6.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel

import config
from pooldesk import db
from pooldesk.data_quality import OUTLIER_MOVE_THRESHOLD

ROOT_CAUSES = ("UNSETTLED_TRADE", "CORPORATE_ACTION", "PRICING_ERROR",
               "TIMING_DIFFERENCE", "DATA_ENTRY_ERROR", "FX_MISMATCH",
               "UNKNOWN")
OWNER_TEAMS = ("Trade Settlement", "Pricing", "Fund Accounting", "Custody",
               "Data Management")

_SYSTEM_PROMPT = """You are an Investment Operations reconciliation analyst.

You triage position breaks between an internal book of record and a
custodian feed. For each break you receive structured context (break type,
quantity difference, CAD market-value impact, severity, recent trades on the
security, and data-quality flags). For each break, return:

- root_cause: one of UNSETTLED_TRADE, CORPORATE_ACTION, PRICING_ERROR,
  TIMING_DIFFERENCE, DATA_ENTRY_ERROR, FX_MISMATCH, UNKNOWN.
- owner_team: the team best placed to resolve it — Trade Settlement, Pricing,
  Fund Accounting, Custody, or Data Management.
- priority: P1 (HIGH severity / urgent), P2 (MEDIUM), P3 (LOW).
- resolution_note: 1-2 concise sentences telling the owner team what to check.

Guidance:
- A PENDING trade on the security usually means UNSETTLED_TRADE (Trade Settlement).
- A missing/zero price or stale price points to PRICING_ERROR (Pricing).
- A non-CAD security with no FX rate points to FX_MISMATCH (Pricing).
- A position the custodian has but the internal book does not (MISSING_IN_INTERNAL)
  is usually DATA_ENTRY_ERROR (Data Management).
- A plain quantity difference with no other signal is typically a
  TIMING_DIFFERENCE (Fund Accounting).
Be specific and practical. Do not invent facts beyond the context given."""


class BreakAnalysis(BaseModel):
    """One break's triage result."""
    break_id: str
    root_cause: Literal["UNSETTLED_TRADE", "CORPORATE_ACTION", "PRICING_ERROR",
                        "TIMING_DIFFERENCE", "DATA_ENTRY_ERROR", "FX_MISMATCH",
                        "UNKNOWN"]
    owner_team: Literal["Trade Settlement", "Pricing", "Fund Accounting",
                        "Custody", "Data Management"]
    priority: Literal["P1", "P2", "P3"]
    resolution_note: str


class AnalysisBatch(BaseModel):
    """The full set of analyses returned for one day."""
    analyses: list[BreakAnalysis]


# ── context building ────────────────────────────────────────────────────────
def build_context(break_row: pd.Series, run_date: date) -> dict:
    """Assemble the evidence the classifier needs for one break."""
    diso = run_date.isoformat()
    sid = break_row["security_id"]

    sec = db.query(
        "SELECT name, currency FROM dim_security WHERE security_id=?", (sid,))
    currency = sec.currency.iloc[0] if not sec.empty else "USD"
    name = sec.name.iloc[0] if not sec.empty else sid

    trades = db.query(
        "SELECT trade_id, trade_date, side, quantity, status, settlement_date "
        "FROM fact_trade WHERE security_id=? AND feed_date<=? "
        "ORDER BY feed_date DESC LIMIT 6", (sid, diso))
    has_pending_trade = bool((trades.status == "PENDING").any())

    # Price data-quality signals — missing, non-positive, stale, or an
    # implausible outlier all point to a pricing problem.
    price = db.query(
        "SELECT price, price_timestamp FROM fact_price "
        "WHERE feed_date=? AND security_id=?", (diso, sid))
    price_missing = price.empty
    price_nonpositive = (not price.empty) and bool((price.price <= 0).any())
    price_stale = (not price.empty) and bool(
        (price.price_timestamp.str[:10] < diso).any())
    price_outlier = False
    prior = config.prior_business_day(run_date)
    if not price.empty and prior is not None:
        prev = db.query(
            "SELECT AVG(price) AS p FROM fact_price WHERE feed_date=? "
            "AND security_id=? AND price>0", (prior.isoformat(), sid))
        base = prev.p.iloc[0] if not prev.empty else None
        if base and base > 0:
            price_outlier = any(
                px > 0 and abs(px / base - 1) > OUTLIER_MOVE_THRESHOLD
                for px in price.price)
    price_bad = price_nonpositive or price_stale or price_outlier

    fx_missing = False
    if currency != config.BASE_CURRENCY:
        fx = db.query("SELECT 1 FROM fact_fx WHERE feed_date=? AND from_ccy=?",
                      (diso, currency))
        fx_missing = fx.empty

    return {
        "break_id": break_row["break_id"],
        "pool_id": break_row["pool_id"],
        "security_id": sid,
        "security_name": name,
        "currency": currency,
        "break_type": break_row["break_type"],
        "qty_diff": float(break_row["qty_diff"]),
        "mv_impact_cad": float(break_row["mv_impact_cad"]),
        "severity": break_row["severity"],
        "has_pending_trade": has_pending_trade,
        "price_missing": price_missing,
        "price_bad": price_bad,
        "price_stale": price_stale,
        "price_outlier": price_outlier,
        "fx_missing": fx_missing,
        "recent_trades": trades.to_dict("records"),
    }


# ── rule-based fallback ─────────────────────────────────────────────────────
_PRIORITY_BY_SEVERITY = {"HIGH": "P1", "MEDIUM": "P2", "LOW": "P3"}

_NOTE_BY_CAUSE = {
    "UNSETTLED_TRADE": "A pending trade on this security has not settled — "
                       "confirm settlement status with the custodian and "
                       "re-run the reconciliation once settled.",
    "FX_MISMATCH": "The day's FX rate for this currency is missing — supply "
                   "the rate, then revalue and re-reconcile.",
    "PRICING_ERROR": "The market price for this security is missing or "
                     "invalid — source a clean price before resolving.",
    "DATA_ENTRY_ERROR": "The custodian reports a position the internal book "
                        "does not — verify the booking and correct the book "
                        "of record.",
    "TIMING_DIFFERENCE": "Quantities differ with no other signal — likely a "
                         "timing difference; confirm against the trade "
                         "blotter and cut-off.",
    "CORPORATE_ACTION": "Check for an unprocessed corporate action on this "
                        "security.",
    "UNKNOWN": "Root cause unclear — investigate the position history and "
               "escalate if unresolved.",
}


def _classify_rule_based(ctx: dict) -> BreakAnalysis:
    """Deterministic classifier — no API key required."""
    if ctx["break_type"] == "MISSING_IN_INTERNAL":
        cause, team = "DATA_ENTRY_ERROR", "Data Management"
    elif ctx["has_pending_trade"]:
        cause, team = "UNSETTLED_TRADE", "Trade Settlement"
    elif ctx["fx_missing"]:
        cause, team = "FX_MISMATCH", "Pricing"
    elif ctx["price_missing"] or ctx["price_bad"]:
        cause, team = "PRICING_ERROR", "Pricing"
    elif ctx["break_type"] == "MISSING_IN_CUSTODIAN":
        cause, team = "TIMING_DIFFERENCE", "Custody"
    elif ctx["break_type"] == "QUANTITY_MISMATCH":
        cause, team = "TIMING_DIFFERENCE", "Fund Accounting"
    else:
        cause, team = "UNKNOWN", "Fund Accounting"
    return BreakAnalysis(
        break_id=ctx["break_id"],
        root_cause=cause,
        owner_team=team,
        priority=_PRIORITY_BY_SEVERITY.get(ctx["severity"], "P3"),
        resolution_note=_NOTE_BY_CAUSE[cause],
    )


def _analyze_rule_based(contexts: list[dict]) -> list[BreakAnalysis]:
    return [_classify_rule_based(c) for c in contexts]


# ── LLM path ────────────────────────────────────────────────────────────────
def _analyze_with_llm(contexts: list[dict]) -> list[BreakAnalysis]:
    """Classify a day's breaks with one batched, structured Claude call."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    payload = json.dumps({"breaks": contexts}, default=str, indent=2)

    response = client.messages.parse(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        # System prompt is static — cache_control lets repeated daily runs
        # reuse it (prefix caching) once it exceeds the model's minimum.
        system=[{
            "type": "text",
            "text": _SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": f"Triage these reconciliation breaks. Return one "
                       f"analysis per break_id.\n\n{payload}",
        }],
        output_format=AnalysisBatch,
    )
    batch = response.parsed_output
    if batch is None:
        raise ValueError("structured output returned no parsed result")
    return batch.analyses


# ── orchestration ───────────────────────────────────────────────────────────
def analyze_exceptions(run_date: date) -> pd.DataFrame:
    """Triage every OPEN break for a day and persist the AI fields.

    Returns the analyses as a DataFrame. Breaks remain OPEN — the assistant
    triages, a human resolves.
    """
    diso = run_date.isoformat()
    breaks = db.query(
        "SELECT * FROM recon_exception WHERE run_date=? AND status='OPEN'",
        (diso,))
    if breaks.empty:
        return pd.DataFrame(columns=["break_id", "root_cause", "owner_team",
                                     "priority", "resolution_note", "mode"])

    contexts = [build_context(row, run_date)
                for _, row in breaks.iterrows()]

    mode = "rule_based"
    analyses: list[BreakAnalysis] = []
    if config.has_live_ai():
        try:
            analyses = _analyze_with_llm(contexts)
            mode = "llm"
        except Exception as exc:                      # any API / parse failure
            print(f"[ai_assistant] LLM path failed ({exc}); "
                  f"falling back to rule-based classifier")
            analyses = []

    by_id = {a.break_id: a for a in analyses}
    # Any break the LLM skipped (or all of them, in fallback) is rule-based.
    resolved: list[BreakAnalysis] = []
    for ctx in contexts:
        resolved.append(by_id.get(ctx["break_id"]) or _classify_rule_based(ctx))

    with db.get_connection() as conn:
        for a in resolved:
            conn.execute(
                "UPDATE recon_exception SET ai_root_cause=?, "
                "ai_resolution_note=?, ai_owner_team=?, ai_priority=? "
                "WHERE break_id=?",
                (a.root_cause, a.resolution_note, a.owner_team, a.priority,
                 a.break_id))

    print(f"[ai_assistant] triaged {len(resolved)} break(s) for {diso} "
          f"({mode})")
    out = pd.DataFrame([a.model_dump() for a in resolved])
    out["mode"] = mode
    return out
