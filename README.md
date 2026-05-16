# PoolDesk

**A simulated Investment Operations daily-workflow automation suite** — data
ingestion, quality control, reconciliation, NAV, AI-assisted exception triage
and reporting, wired into one pipeline.

> Built as a portfolio project for an Investment Operations (AI, Data and
> Process Optimization) internship. It is a **learning simulation, not a
> production system** — the operational data is synthetic by design (see
> [Design decisions](#design-decisions)).

## What it is

PoolDesk models the back/middle-office workflow of an institutional asset
manager that pools client money into asset-class funds. Each business day it:

1. **Ingests** six feeds (prices, FX, internal positions, custodian positions,
   trades, cash) into SQLite.
2. **Checks data quality** — 7 checks, a 0-100 scorecard.
3. **Reconciles** the internal book against the custodian and classifies every
   break by CAD market-value impact.
4. **Computes NAV**, unit prices, per-client holdings and daily P&L.
5. **Triages exceptions with AI** — root cause, owner team, priority and a
   drafted resolution note (Claude API, with a deterministic fallback).
6. **Reports** — a seven-tab Excel ops pack, a one-page PDF, weekly/monthly
   roll-ups, CSV extracts for Power BI, and an auto-generated Power BI-style
   HTML dashboard (`reports/dashboard.html`).

A Power Automate flow then distributes the pack and escalates HIGH-severity
breaks. See [`docs/process_flow.md`](docs/process_flow.md) for the full flow.

## Architecture

```
data/feeds ─▶ ingest ─▶ data quality ─▶ reconcile ─▶ NAV ─▶ AI triage ─▶ reporting
   (CSV)       (SQLite)   (scorecard)    (breaks)   (unit px)  (Claude)   (xlsx/pdf)
                                                                              │
                                            Power Automate ◀──────────────────┘
                                          (email · Teams · SharePoint log)
```

Modelled on a real pooled-fund manager: **5 asset-class pools** (equity, fixed
income, private equity, real estate, infrastructure), **34 securities** (real
tickers), **5 clients**, **30 business days** of synthetic activity.

## Tech stack

Python 3.11+ · pandas · SQLite · openpyxl · fpdf2 · matplotlib ·
Anthropic SDK (Claude) · SQL · VBA · Power BI · Power Automate.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: add ANTHROPIC_API_KEY for the LLM path

python main.py generate       # build reference data + 30 days of feeds
python main.py init-db        # create the SQLite schema, load reference data
python main.py run-all        # run every business day end to end
```

`run-all` completes in a few seconds and writes the daily packs to `reports/`.
**No API key is required** — the AI assistant falls back to a rule-based
classifier, and market data is generated offline. Set `ANTHROPIC_API_KEY` in
`.env` to enable the live LLM triage path, or `MARKET_DATA_MODE=live` for real
prices via yfinance.

`run-all` also writes `reports/dashboard.html` — a self-contained Power BI-style
dashboard that opens in any browser. Other commands: `run --date YYYY-MM-DD`,
`report --date ...`, `rollup --week ... / --month ...`, `export`, `dashboard`.

## What it demonstrates

| Role requirement | Where in PoolDesk |
|---|---|
| AI-powered automation | `ai_assistant.py` — LLM exception triage with fallback |
| Python scripting | the whole pipeline |
| SQL | `sql/schema.sql`, `sql/checks.sql` (7 recon/DQ queries) |
| VBA | `excel/VBA_Macro.bas` |
| Power BI / Power Automate | `powerbi/README.md`, `automate/flow_spec.md` |
| Data quality management | `data_quality.py` — 7 checks + scorecard |
| Reconciliation / pool oversight | `reconcile.py` |
| Financial analysis (NAV) | `nav.py` |
| Daily/weekly/monthly reporting | `reporting.py` |
| Process documentation & controls | `docs/` |

## Project layout

```
config.py                 .env-driven settings
main.py                   pipeline orchestrator (CLI)
pooldesk/                  reference, generators, ingest, DQ, reconcile,
                           nav, ai_assistant, reporting, db
sql/                       schema.sql, checks.sql
excel/  powerbi/  automate/ VBA macro, Power BI guide, Power Automate spec
docs/                      process flow, runbook, control matrix, AI framework
tests/                     pytest suite (data quality, reconcile, NAV)
data/ reports/             generated (git-ignored)
```

## Design decisions

- **Real tickers, synthetic operations data.** Securities use real tickers
  mapped to the five asset classes; the operational book (positions, trades,
  custodian records, client holdings) is fully synthetic — a real book is
  confidential and has no public dataset. Operations data is *inherently*
  internal.
- **Deliberate data issues.** The generator injects missing/stale/outlier/
  duplicate prices, FX gaps and reconciliation breaks (all seed-reproducible)
  so the quality and reconciliation engines have something real to find.
- **Listed proxies for private assets.** Private equity, real estate and
  infrastructure use listed proxies (BDCs, REITs, infra holdcos) so the whole
  workflow can be simulated with daily prices — a documented simplification.
- **Runs anywhere.** Offline by default, no API key required; the AI module
  degrades gracefully to a rule-based classifier.
- **AI triages, humans resolve.** The assistant never closes a break — it
  classifies and drafts; resolution stays a human decision.

See [`docs/`](docs/) for a plain-language guide ([`GUIDE.md`](docs/GUIDE.md) —
glossary, data, queries and logic explained simply), the process flow, runbook,
control matrix and the AI-driven operational implementation framework. Full
design rationale is in [`BUILD_SPEC.md`](BUILD_SPEC.md).

---
*PoolDesk is an independent learning simulation. It is not affiliated with, and
uses no data from, any asset manager.*
