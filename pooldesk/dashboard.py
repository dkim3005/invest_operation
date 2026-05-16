"""Module 15 — auto-generated Power BI-style HTML dashboard.

Renders the pipeline's results as a single self-contained ``dashboard.html``
— KPI cards, donut / bar / line charts, a treemap and a top-breaks table,
styled to look like a Power BI report. Plotly is embedded inline so the file
opens in any browser with no network or Power BI licence. See BUILD_SPEC.md.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from string import Template

import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

import config
from pooldesk import data_quality, db

# ── Power BI-flavoured palette ───────────────────────────────────────────────
BLUE = "#118DFF"
SEV_COLOR = {"HIGH": "#D64550", "MEDIUM": "#E8A33D", "LOW": "#4C9A6B"}
BAR_PALETTE = ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#3FA66A"]

_BASE_LAYOUT = dict(
    margin=dict(l=14, r=14, t=8, b=14),
    height=240,
    template="plotly_white",
    font=dict(family="Segoe UI, Arial, sans-serif", size=11, color="#323130"),
    paper_bgcolor="white",
    plot_bgcolor="white",
)
_PLOT_CONFIG = {"displayModeBar": False, "responsive": True}


def _div(fig: go.Figure) -> str:
    """Render a figure as an embeddable HTML div (plotly.js loaded once)."""
    return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                       config=_PLOT_CONFIG)


# ── individual visuals ───────────────────────────────────────────────────────
def _fig_severity_donut() -> str:
    rows = (db.query("SELECT severity, COUNT(*) AS n FROM recon_exception "
                     "GROUP BY severity")
            .set_index("severity").reindex(["HIGH", "MEDIUM", "LOW"])
            .fillna(0).reset_index())
    fig = go.Figure(go.Pie(
        labels=rows.severity, values=rows.n, hole=0.58, sort=False,
        marker=dict(colors=[SEV_COLOR[s] for s in rows.severity]),
        textinfo="value"))
    fig.update_layout(**_BASE_LAYOUT,
                      legend=dict(orientation="h", y=-0.05, x=0.5,
                                  xanchor="center"))
    return _div(fig)


def _fig_breaks_by_type() -> str:
    rows = db.query("SELECT break_type, COUNT(*) AS n FROM recon_exception "
                    "GROUP BY break_type ORDER BY n")
    fig = go.Figure(go.Bar(
        x=rows.n, y=rows.break_type, orientation="h", marker_color=BLUE,
        text=rows.n, textposition="auto"))
    fig.update_layout(**_BASE_LAYOUT, showlegend=False)
    fig.update_xaxes(title_text="break count")
    return _div(fig)


def _fig_nav_trend() -> str:
    rows = db.query("SELECT nav_date, SUM(nav_cad)/1e6 AS t FROM fact_nav "
                    "GROUP BY nav_date ORDER BY nav_date")
    fig = go.Figure(go.Scatter(
        x=rows.nav_date, y=rows.t, mode="lines+markers",
        line=dict(color=BLUE, width=2.4), fill="tozeroy",
        fillcolor="rgba(17,141,255,0.12)"))
    fig.update_layout(**_BASE_LAYOUT, showlegend=False)
    fig.update_yaxes(title_text="total NAV (CAD m)")
    return _div(fig)


def _fig_dq_trend() -> str:
    rows = db.query("SELECT run_date, AVG(pass_rate)*100 AS score "
                    "FROM dq_result GROUP BY run_date ORDER BY run_date")
    fig = go.Figure(go.Scatter(
        x=rows.run_date, y=rows.score, mode="lines+markers",
        line=dict(color="#4C9A6B", width=2.4)))
    fig.update_layout(**_BASE_LAYOUT, showlegend=False)
    fig.update_yaxes(title_text="DQ score", range=[
        max(0, float(rows.score.min()) - 5), 100])
    return _div(fig)


def _fig_nav_by_pool(as_of: str) -> str:
    rows = db.query(
        "SELECT p.pool_name, n.nav_cad/1e6 AS v FROM fact_nav n "
        "JOIN dim_pool p ON p.pool_id = n.pool_id "
        "WHERE n.nav_date=? ORDER BY v DESC", (as_of,))
    fig = go.Figure(go.Bar(
        x=rows.pool_name, y=rows.v,
        marker_color=BAR_PALETTE[:len(rows)],
        text=rows.v.round(1), textposition="auto"))
    fig.update_layout(**_BASE_LAYOUT, showlegend=False)
    fig.update_yaxes(title_text="NAV (CAD m)")
    return _div(fig)


def _fig_client_treemap(as_of: str) -> str:
    rows = db.query(
        "SELECT c.client_name, SUM(h.holding_value_cad) AS v "
        "FROM fact_client_holding h JOIN dim_client c "
        "ON c.client_id = h.client_id WHERE h.holding_date=? "
        "GROUP BY c.client_name ORDER BY v DESC", (as_of,))
    fig = go.Figure(go.Treemap(
        labels=rows.client_name, parents=[""] * len(rows), values=rows.v,
        marker=dict(colors=BAR_PALETTE[:len(rows)]),
        texttemplate="%{label}<br>CAD %{value:,.0f}"))
    fig.update_layout(**_BASE_LAYOUT)
    return _div(fig)


def _top_breaks_table() -> str:
    rows = db.query(
        "SELECT run_date, pool_id, security_id, break_type, severity, "
        "mv_impact_cad, ai_root_cause, ai_owner_team FROM recon_exception "
        "ORDER BY mv_impact_cad DESC LIMIT 8")
    body = []
    for r in rows.itertuples(index=False):
        body.append(
            f"<tr><td>{r.run_date}</td><td>{r.pool_id}</td>"
            f"<td>{r.security_id}</td><td>{r.break_type}</td>"
            f"<td class='sev-{r.severity}'>{r.severity}</td>"
            f"<td class='num'>{r.mv_impact_cad:,.0f}</td>"
            f"<td>{r.ai_root_cause or ''}</td>"
            f"<td>{r.ai_owner_team or ''}</td></tr>")
    return "\n".join(body)


# ── page assembly ────────────────────────────────────────────────────────────
_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>PoolDesk — Investment Operations Dashboard</title>
<script>$plotlyjs</script>
<style>
 *{box-sizing:border-box;}
 body{margin:0;background:#f3f2f1;font-family:'Segoe UI',Arial,sans-serif;color:#252423;}
 .header{background:#1b2a4a;color:#fff;padding:14px 24px;display:flex;
   justify-content:space-between;align-items:baseline;}
 .header h1{margin:0;font-size:18px;font-weight:600;}
 .header .asof{font-size:13px;color:#c7d0e0;}
 .wrap{padding:16px 24px 8px;}
 .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px;}
 .card{background:#fff;border-radius:6px;box-shadow:0 1.6px 3.6px rgba(0,0,0,.13);
   padding:14px 16px;}
 .card .label{font-size:11px;color:#605e5c;text-transform:uppercase;letter-spacing:.5px;}
 .card .value{font-size:30px;font-weight:600;margin-top:4px;}
 .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;}
 .tile{background:#fff;border-radius:6px;box-shadow:0 1.6px 3.6px rgba(0,0,0,.13);
   padding:10px 14px;}
 .tile h3{margin:2px 0 2px;font-size:13px;font-weight:600;color:#323130;}
 .tile.wide{grid-column:1 / -1;}
 table{width:100%;border-collapse:collapse;font-size:12px;}
 th{background:#f3f2f1;text-align:left;padding:7px 9px;color:#605e5c;font-weight:600;}
 td{padding:6px 9px;border-bottom:1px solid #edebe9;}
 td.num{text-align:right;font-variant-numeric:tabular-nums;}
 .sev-HIGH{color:#D64550;font-weight:600;}
 .sev-MEDIUM{color:#9a6a00;font-weight:600;}
 .sev-LOW{color:#4C9A6B;}
 .footer{padding:8px 24px 16px;font-size:11px;color:#a19f9d;}
</style></head>
<body>
 <div class="header">
   <h1>PoolDesk &mdash; Investment Operations Dashboard</h1>
   <div class="asof">As of $as_of &middot; 30-day simulation window</div>
 </div>
 <div class="wrap">
   <div class="kpis">
     <div class="card"><div class="label">Data Quality Score</div>
       <div class="value" style="color:$dq_color">$kpi_dq</div></div>
     <div class="card"><div class="label">Total NAV</div>
       <div class="value" style="color:#118DFF">$kpi_nav</div></div>
     <div class="card"><div class="label">Open Breaks</div>
       <div class="value" style="color:#1b2a4a">$kpi_open</div></div>
     <div class="card"><div class="label">High-Severity Breaks</div>
       <div class="value" style="color:$high_color">$kpi_high</div></div>
   </div>
   <div class="grid">
     <div class="tile"><h3>Breaks by severity (window)</h3>$donut</div>
     <div class="tile"><h3>Breaks by type (window)</h3>$bartypes</div>
     <div class="tile"><h3>Total NAV trend</h3>$navtrend</div>
     <div class="tile"><h3>Data quality score trend</h3>$dqtrend</div>
     <div class="tile"><h3>NAV by pool (as of $as_of)</h3>$navpool</div>
     <div class="tile"><h3>Client holdings (as of $as_of)</h3>$treemap</div>
     <div class="tile wide"><h3>Top reconciliation breaks by market-value impact</h3>
       <table><thead><tr><th>Run date</th><th>Pool</th><th>Security</th>
       <th>Break type</th><th>Severity</th><th>MV impact (CAD)</th>
       <th>AI root cause</th><th>Owner team</th></tr></thead>
       <tbody>$table</tbody></table></div>
   </div>
 </div>
 <div class="footer">Auto-generated by PoolDesk &middot; learning portfolio
   simulation &middot; operational data is synthetic.</div>
</body></html>
""")


def build_dashboard(out_path: Path | None = None) -> Path:
    """Build the self-contained Power BI-style HTML dashboard."""
    as_of = db.query("SELECT MAX(nav_date) AS d FROM fact_nav").d.iloc[0]
    if as_of is None:
        raise RuntimeError("no NAV data — run the pipeline before the dashboard")

    total_nav = float(db.query(
        "SELECT COALESCE(SUM(nav_cad),0) AS s FROM fact_nav WHERE nav_date=?",
        (as_of,)).s.iloc[0])
    score = data_quality.dq_scorecard(date.fromisoformat(as_of))["overall_score"]
    # KPIs count only OPEN breaks — they measure outstanding work.
    sev = dict(db.query(
        "SELECT severity, COUNT(*) AS n FROM recon_exception "
        "WHERE run_date=? AND status='OPEN' GROUP BY severity",
        (as_of,)).itertuples(index=False, name=None))
    open_breaks = sum(sev.values())
    high_breaks = sev.get("HIGH", 0)

    html = _TEMPLATE.substitute(
        plotlyjs=get_plotlyjs(),
        as_of=as_of,
        kpi_dq=f"{score:.1f}",
        dq_color="#4C9A6B" if score >= 95 else "#9a6a00" if score >= 90
        else "#D64550",
        kpi_nav=f"CAD {total_nav / 1e6:,.1f}M",
        kpi_open=str(open_breaks),
        kpi_high=str(high_breaks),
        high_color="#D64550" if high_breaks else "#4C9A6B",
        donut=_fig_severity_donut(),
        bartypes=_fig_breaks_by_type(),
        navtrend=_fig_nav_trend(),
        dqtrend=_fig_dq_trend(),
        navpool=_fig_nav_by_pool(as_of),
        treemap=_fig_client_treemap(as_of),
        table=_top_breaks_table(),
    )

    out = out_path or (config.REPORTS_DIR / "dashboard.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[dashboard] wrote {out}")
    return out
