# PoolDesk — Power BI dashboard (Module 11)

A build guide for the **PoolDesk Operations Dashboard**. The binary `.pbix` is
not version-controlled (it is environment-specific); this guide plus the CSV
exports reproduce it exactly. It demonstrates the **Power BI** skill the role
asks for.

## 1. Produce the data

```bash
python main.py run-all      # runs the pipeline and writes the exports
# or, if the pipeline has already run:
python main.py export
```

This writes eight CSVs to `reports/powerbi/`:

| File | Role |
|---|---|
| `fact_nav.csv` | per-pool NAV, unit price |
| `fact_client_holding.csv` | per-client holding value |
| `recon_exception.csv` | reconciliation breaks + AI triage |
| `dq_result.csv` | data-quality check results |
| `fact_trade.csv` | trade blotter |
| `dim_pool.csv`, `dim_client.csv`, `dim_security.csv` | dimensions |
| `dim_date.csv` | shared date dimension (one row per calendar day) |

## 2. Load into Power BI Desktop

**Get Data → Folder** → select `reports/powerbi/`, or **Get Data → Text/CSV**
for each file. In Power Query, set the date columns — `dim_date[date]`,
`fact_nav[nav_date]`, `recon_exception[run_date]`, `dq_result[run_date]`,
`fact_client_holding[holding_date]`, `fact_trade[feed_date]` — all to **Date**
type (the same type on both sides of every relationship), then
**Close & Apply**.

## 3. Model the relationships

In **Model view**, create these one-to-many relationships (single direction).
The `dim_date` relationships are what let one date slicer filter every page.

| From (1) | To (many) |
|---|---|
| `dim_date[date]` | `fact_nav[nav_date]` |
| `dim_date[date]` | `recon_exception[run_date]` |
| `dim_date[date]` | `dq_result[run_date]` |
| `dim_date[date]` | `fact_client_holding[holding_date]` |
| `dim_date[date]` | `fact_trade[feed_date]` |
| `dim_pool[pool_id]` | `fact_nav[pool_id]` |
| `dim_pool[pool_id]` | `fact_client_holding[pool_id]` |
| `dim_pool[pool_id]` | `recon_exception[pool_id]` |
| `dim_pool[pool_id]` | `fact_trade[pool_id]` |
| `dim_client[client_id]` | `fact_client_holding[client_id]` |
| `dim_security[security_id]` | `recon_exception[security_id]` |
| `dim_security[security_id]` | `fact_trade[security_id]` |

## 4. DAX measures

Create these in a dedicated **Measures** table:

```DAX
Total NAV (CAD)      = SUM ( fact_nav[nav_cad] )
DQ Score             = AVERAGE ( dq_result[pass_rate] ) * 100
Failed DQ Records    = SUM ( dq_result[records_failed] )
Open Breaks          = CALCULATE ( COUNTROWS ( recon_exception ),
                                   recon_exception[status] = "OPEN" )
High Severity Breaks = CALCULATE ( COUNTROWS ( recon_exception ),
                                   recon_exception[severity] = "HIGH" )
MV Impact (CAD)      = SUM ( recon_exception[mv_impact_cad] )
Pending Trades       = CALCULATE ( COUNTROWS ( fact_trade ),
                                   fact_trade[status] = "PENDING" )
```

## 5. Report pages

### Page 1 — Ops Control
- **Cards**: `DQ Score`, `Open Breaks`, `High Severity Breaks`, `Total NAV (CAD)`
- **Donut**: count of breaks by `severity`
- **Line**: `Open Breaks` by `dim_date[date]` (break trend)
- **Line**: `Total NAV (CAD)` by `dim_date[date]`

### Page 2 — Reconciliation
- **Bar**: count of breaks by `break_type`
- **Bar**: count of breaks by `ai_owner_team`
- **Matrix**: `break_type` (rows) × `severity` (columns), value = count
- **Table**: top breaks — `break_id`, `pool_id`, security `name`, `break_type`,
  `severity`, `mv_impact_cad`, `ai_root_cause`, `ai_owner_team`, sorted by
  `MV Impact (CAD)` descending

### Page 3 — NAV & Clients
- **Bar**: `Total NAV (CAD)` by `pool_name`
- **Treemap**: `holding_value_cad` by `client_name`
- **Line**: `fact_nav[unit_price]` by `dim_date[date]`, legend = `pool_name`
- **Table**: client holdings — `client_name`, `pool_name`, `units_held`,
  `holding_value_cad`

## 6. Slicers

Add a `dim_date[date]` slicer, a `pool_name` slicer and an `asset_class`
slicer (both from `dim_pool`). Because every fact table relates to `dim_date`
and `dim_pool`, these slicers filter all three pages to a single day, pool or
asset class.

## 7. Refresh

Re-run `python main.py export`, then **Home → Refresh** in Power BI Desktop.

## Note

This is a learning portfolio artifact. In production the dashboard would
connect directly to the database or a data warehouse (DirectQuery) rather than
to CSV extracts.
