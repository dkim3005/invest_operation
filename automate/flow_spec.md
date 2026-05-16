# PoolDesk — Power Automate flow specification (Module 12)

A cloud flow that distributes the daily operations pack and raises an alert
when there are HIGH-severity breaks. It is the automation/notification layer on
top of the Python pipeline and demonstrates the **Power Automate** skill the
role asks for.

A Power Automate flow is a cloud object in an Office 365 tenant, so it cannot
be checked into the repo. This file specifies it precisely enough to rebuild
in the Power Automate designer, step by step.

## What it does

Each business morning, after the pipeline has produced the day's artefacts, the
flow emails the daily PDF to the operations distribution list, posts a summary
to a Teams channel, escalates by email when HIGH-severity breaks exist, and
logs the run to a SharePoint list.

## Prerequisites

1. **`reports/` synced to the cloud.** The pipeline (`python main.py run-all`,
   run on a server / scheduled task / Azure Function before the flow fires)
   writes into a folder that is synced to a **SharePoint document library** or
   **OneDrive for Business**, so the flow's file connectors can read it. The
   flow consumes two files per day:
   - `reports/daily/run_status_YYYYMMDD.json` — machine-readable run summary
   - `reports/daily/PoolDesk_Summary_YYYYMMDD.pdf` — the one-page report
2. A **Microsoft Teams** channel for the operations team.
3. A **SharePoint list** named `PoolDesk Run Log` with columns: `RunDate`
   (Date), `DQScore` (Number), `Breaks` (Number), `BreaksHigh` (Number),
   `TotalNAV` (Number), `Status` (Choice: OK / ATTENTION).

## Trigger

**Recurrence**
- Frequency: `Day`, Interval `1`
- On these days: `Monday, Tuesday, Wednesday, Thursday, Friday`
- At these hours / minutes: `07:30`
- Time zone: `Eastern Standard Time`

## Actions

### 1. Compose — date keys
- Action: **Compose** → name `dateKey`
  - Input: `@{formatDateTime(utcNow(), 'yyyyMMdd')}`
- Action: **Compose** → name `dateIso`
  - Input: `@{formatDateTime(utcNow(), 'yyyy-MM-dd')}`

### 2. Get the run-status file
- Action: **Get file content using path** (SharePoint / OneDrive)
  - File path: `/reports/daily/run_status_@{outputs('dateKey')}.json`

### 3. Parse JSON
- Action: **Parse JSON**
  - Content: output of step 2
  - Schema (generate from a sample run_status file):
    ```json
    {
      "type": "object",
      "properties": {
        "date":        { "type": "string" },
        "dq_score":    { "type": "number" },
        "breaks":      { "type": "integer" },
        "breaks_high": { "type": "integer" },
        "total_nav":   { "type": "number" }
      }
    }
    ```

### 4. Get the daily PDF
- Action: **Get file content using path**
  - File path: `/reports/daily/PoolDesk_Summary_@{outputs('dateKey')}.pdf`

### 5. Email the daily pack
- Action: **Send an email (V2)** (Office 365 Outlook)
  - To: the operations distribution list
  - Subject: `PoolDesk daily pack — @{outputs('dateIso')}`
  - Body: include `dq_score`, `breaks`, `breaks_high`, `total_nav` from the
    Parse JSON output
  - Attachments: name `PoolDesk_Summary_@{outputs('dateKey')}.pdf`,
    content = output of step 4

### 6. Post to Teams
- Action: **Post message in a chat or channel** (Microsoft Teams)
  - Post as: `Flow bot`, in the operations channel
  - Message: `PoolDesk @{outputs('dateIso')} — DQ score
    @{body('Parse_JSON')?['dq_score']}, @{body('Parse_JSON')?['breaks']}
    break(s), @{body('Parse_JSON')?['breaks_high']} HIGH.`

### 7. Condition — HIGH-severity escalation
- Control: **Condition**
  - Expression: `body('Parse_JSON')?['breaks_high']` **is greater than** `0`
- **If yes** — Action: **Send an email (V2)**
  - To: the reconciliation team lead
  - Importance: `High`
  - Subject: `ACTION: @{body('Parse_JSON')?['breaks_high']} HIGH-severity
    break(s) — @{outputs('dateIso')}`
  - Body: instruct the team to open the daily Excel ops pack
    (`PoolDesk_Ops_@{outputs('dateKey')}.xlsx`) and clear the HIGH breaks.
- **If no** — no action.

### 8. Log the run to SharePoint
- Action: **Create item** (SharePoint) in `PoolDesk Run Log`
  - `RunDate` = `body('Parse_JSON')?['date']`
  - `DQScore` = `body('Parse_JSON')?['dq_score']`
  - `Breaks` = `body('Parse_JSON')?['breaks']`
  - `BreaksHigh` = `body('Parse_JSON')?['breaks_high']`
  - `TotalNAV` = `body('Parse_JSON')?['total_nav']`
  - `Status` = expression: `if(greater(body('Parse_JSON')?['breaks_high'], 0),
    'ATTENTION', 'OK')`

## Error handling

On steps 2 and 4, set **Configure run after** so a missing file routes to a
final **Send an email (V2)** action that notifies the pipeline owner that the
day's artefacts were not produced — the flow surfaces a pipeline failure
instead of failing silently.

## How this maps to the project

`main.py` writes `reports/daily/run_status_YYYYMMDD.json` at the end of every
day's pipeline run — that file is the contract between the Python pipeline and
this flow. Splitting it this way (Python does the heavy processing, Power
Automate does the scheduled trigger and the Office 365 distribution) is the
recommended pattern: Power Automate for low-maintenance O365 workflows, Python
for the computation. This is a learning portfolio artifact.
