# PoolDesk — daily operations process flow

The daily Investment Operations workflow PoolDesk automates, end to end.

```mermaid
flowchart TD
    subgraph Sources [Daily feeds]
        F1[Market prices]
        F2[FX rates]
        F3[Internal positions]
        F4[Custodian positions]
        F5[Trades]
        F6[Cash ledger]
    end

    Sources --> ING[1. Ingest feeds into SQLite]
    ING --> DQ[2. Data quality checks - 7 checks, 0-100 scorecard]
    DQ --> REC[3. Reconcile internal book vs custodian]
    REC --> NAV[4. NAV, unit price, client holdings]
    NAV --> AI[5. AI exception triage - root cause, owner, priority]
    AI --> REP[6. Reporting - daily Excel pack and PDF summary]
    REP --> DIST[7. Power Automate - email, Teams, SharePoint log]

    REC -->|HIGH-severity breaks| DIST
    DQ -.->|score and failed records| REP
    AI -.->|breaks stay OPEN - human resolves| REC
```

## Step notes

| Step | Module | What happens |
|---|---|---|
| 1 Ingest | `ingest.py` | Six feed files per business day land in SQLite, atomically. |
| 2 Data quality | `data_quality.py` | Schema, completeness, staleness, outlier, duplicate, referential integrity and FX checks; a 0-100 scorecard. |
| 3 Reconcile | `reconcile.py` | Internal vs custodian positions; breaks classified and sized by CAD market-value impact. |
| 4 NAV | `nav.py` | Pool NAV, unit price, per-client holding value, daily P&L — on scrubbed prices. |
| 5 AI triage | `ai_assistant.py` | Each open break gets a probable root cause, owner team, priority and resolution note. |
| 6 Reporting | `reporting.py` | Six-tab Excel ops pack, one-page PDF, weekly/monthly roll-ups. |
| 7 Distribute | `automate/flow_spec.md` | The flow emails the pack, posts to Teams, escalates HIGH breaks, logs the run. |

The orchestrator (`main.py`) runs steps 1-6 in order and logs each step's
duration to `reports/pipeline.log`. Breaks are **triaged** by the AI, never
auto-resolved — resolution stays a human decision (human-in-the-loop).
