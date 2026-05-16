# PoolDesk — control matrix

The operational risks in the daily Investment Operations workflow, the control
that addresses each one, how often it runs, and the evidence it leaves behind.

| # | Risk | Control | Type | Frequency | Evidence |
|---|---|---|---|---|---|
| C1 | A feed arrives with missing columns or null key fields | Schema validation rejects/flags rows with null required fields across all six feed tables | Detective | Daily | `dq_result` row `schema_validation` |
| C2 | A held security has no price, so its position cannot be valued | Price completeness check compares held securities to priced securities | Detective | Daily | `dq_result` row `price_completeness` |
| C3 | A stale price is used as if current | Staleness check flags prices whose timestamp predates the run date | Detective | Daily | `dq_result` row `price_staleness` |
| C4 | A bad tick (zero, negative, or an implausible jump) distorts NAV | Outlier check flags it; NAV values on a scrubbed price that carries the last good price forward | Detective + Preventive | Daily | `dq_result` row `price_outlier`; `nav.py` scrubbing |
| C5 | A duplicated price row double-counts a security | Duplicate check on `(security_id, price_date)` | Detective | Daily | `dq_result` row `price_duplicate` |
| C6 | A position references a security or pool not in the masters | Referential integrity check against `dim_security` / `dim_pool` | Detective | Daily | `dq_result` row `referential_integrity` |
| C7 | A non-base-currency holding is valued without an FX rate | FX completeness check; NAV carries the last known rate forward across a gap | Detective + Preventive | Daily | `dq_result` row `fx_completeness` |
| C8 | The internal book and the custodian disagree on a position | Position reconciliation classifies and sizes every break by CAD impact | Detective | Daily | `recon_exception` rows |
| C9 | A material break is missed among many small ones | Severity is set by market-value impact, not row count, so HIGH breaks surface first | Detective | Daily | `recon_exception.severity` |
| C10 | The cash ledger is internally inconsistent | Cash reconciliation: ledger identity, settlement tie-out vs trades, day-to-day continuity | Detective | Daily | Cash Reconciliation tab of the daily Excel pack |
| C11 | A break is auto-resolved incorrectly by automation | AI assistant only triages — breaks stay `OPEN`; resolution is a human decision (human-in-the-loop) | Preventive | Daily | `recon_exception.status` stays `OPEN`; `ai_*` columns populated |
| C12 | A HIGH-severity break goes unnoticed | Power Automate escalates HIGH breaks by priority email and logs the run | Detective | Daily | `automate/flow_spec.md` step 7; `PoolDesk Run Log` |
| C13 | A pipeline step fails silently | Each step is timed and logged; failures raise and are recorded | Detective | Daily | `reports/pipeline.log` |
| C14 | A re-run double-counts data | Every load is idempotent (delete-by-date then insert, single transaction) | Preventive | Every run | `ingest.load_feed_day`, all `write_*` functions |

**Control types** — *Preventive* stops a bad outcome before it happens;
*Detective* surfaces it after the fact for follow-up.

This matrix is a learning portfolio artifact; a production control framework
would also cover access, change management and a maker-checker approval step.
