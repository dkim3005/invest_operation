# PoolDesk — operations runbook

How to run the daily pipeline, what each outcome means, and how to respond when
a step fails. Written as the procedure an operations analyst would follow.

## Daily procedure

1. **Refresh feeds** (simulation): `python main.py generate` produces the
   reference data and the daily feed files. In a real deployment this step is
   replaced by the actual custodian / market-data feeds landing in `data/`.
2. **Run the day**: `python main.py run --date YYYY-MM-DD`, or
   `python main.py run-all` for the whole window. The pipeline runs
   ingest → data quality → reconcile → NAV → AI triage → reporting.
3. **Review the pack**: open `reports/daily/PoolDesk_Ops_YYYYMMDD.xlsx`.
   Start at the **Summary** tab, then **Reconciliation Exceptions**.
4. **Clear HIGH breaks**: every HIGH-severity break must be investigated and
   resolved the same day. Use the AI root cause / owner team as the starting
   point, not the final answer.
5. **Confirm distribution**: the Power Automate flow emails the pack and logs
   the run to the `PoolDesk Run Log` SharePoint list.

## Reading the outcome

| Signal | Where | Healthy | Investigate |
|---|---|---|---|
| Data quality score | Summary tab / `dq_result` | ≥ 95 | < 90, or any HIGH-severity check failing |
| Reconciliation breaks | Reconciliation Exceptions tab | only LOW/MEDIUM | any HIGH break |
| NAV continuity | NAV by Pool tab | unit price moves with the market | an abrupt jump |
| Trades | Trade Blotter tab | mostly SETTLED | FAILED trades, or PENDING past settlement |

## Failure response

| Symptom | Likely cause | Action |
|---|---|---|
| `FileNotFoundError: no feed folder` | feeds for that date were not generated | re-run `python main.py generate`; confirm the date is inside the simulation window |
| A pipeline step logs `FAILED` in `reports/pipeline.log` | bad input data or a code error | read the traceback in the log; the feed-day load is atomic, so re-run the day after fixing |
| Data quality score collapses | a feed arrived malformed or empty | check the DQ Scorecard tab for the failing check and its detail |
| AI assistant logs `LLM path failed ... falling back` | API key missing/invalid or network issue | expected when `ANTHROPIC_API_KEY` is a placeholder — the rule-based classifier still triages every break; supply a key to enable the LLM path |
| Cash reconciliation reports a BREAK | settlement or FX inconsistency | check the Trade Blotter and FX rows for that pool/day |

## Retry & idempotency

Every step is **idempotent** — re-running a day deletes that day's rows and
re-inserts them, so re-running after a fix never doubles up data. `run --date`
also re-processes any missing earlier day so NAV fee accrual stays correct.

## Escalation

| Severity | Who | When |
|---|---|---|
| HIGH break | Reconciliation team lead | same business day |
| Data quality score < 90 | Data Management | same business day |
| Pipeline step FAILED | Pipeline owner | immediately |

(Contacts are illustrative — this is a learning portfolio project.)
