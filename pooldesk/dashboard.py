"""Module 15 — auto-generated operations dashboard (HTML).

Renders the pipeline's results as a single self-contained ``dashboard.html``.
The design goal is *intuitive for a non-expert*: a plain-language narrative
band explains the day in words, every KPI carries a status and a plain
sub-label, and every chart has a one-line "what this shows" caption. Plotly is
embedded inline so the file opens in any browser with no network. See
BUILD_SPEC.md and docs/GUIDE.md.
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

# ── palette ──────────────────────────────────────────────────────────────────
BLUE = "#2563EB"
GREEN = "#1E9E5A"
AMBER = "#C77700"
RED = "#D64550"
SEV_COLOR = {"HIGH": RED, "MEDIUM": AMBER, "LOW": GREEN}
BAR_PALETTE = ["#2563EB", "#1E3A8A", "#E66C37", "#7C3AED", "#1E9E5A"]

_BASE_LAYOUT = dict(
    margin=dict(l=16, r=16, t=8, b=16),
    height=240,
    template="plotly_white",
    font=dict(family="Segoe UI, Arial, sans-serif", size=11, color="#3A3A3A"),
    paper_bgcolor="white",
    plot_bgcolor="white",
)
_PLOT_CONFIG = {"displayModeBar": False, "responsive": True}


def _div(fig: go.Figure) -> str:
    return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                       config=_PLOT_CONFIG)


# ── visuals ──────────────────────────────────────────────────────────────────
def _fig_severity_donut() -> str:
    rows = (db.query("SELECT severity, COUNT(*) AS n FROM recon_exception "
                     "GROUP BY severity")
            .set_index("severity").reindex(["HIGH", "MEDIUM", "LOW"])
            .fillna(0).reset_index())
    fig = go.Figure(go.Pie(
        labels=rows.severity, values=rows.n, hole=0.58, sort=False,
        marker=dict(colors=[SEV_COLOR[s] for s in rows.severity]),
        textinfo="label+value"))
    fig.update_layout(**_BASE_LAYOUT,
                      legend=dict(orientation="h", y=-0.05, x=0.5,
                                  xanchor="center"))
    return _div(fig)


def _fig_breaks_by_type() -> str:
    rows = db.query("SELECT break_type, COUNT(*) AS n FROM recon_exception "
                    "GROUP BY break_type ORDER BY n")
    labels = [t.replace("_", " ").title() for t in rows.break_type]
    fig = go.Figure(go.Bar(x=rows.n, y=labels, orientation="h",
                           marker_color=BLUE, text=rows.n,
                           textposition="auto"))
    fig.update_layout(**_BASE_LAYOUT, showlegend=False)
    fig.update_xaxes(title_text="number of breaks")
    return _div(fig)


def _fig_nav_trend() -> str:
    rows = db.query("SELECT nav_date, SUM(nav_cad)/1e6 AS t FROM fact_nav "
                    "GROUP BY nav_date ORDER BY nav_date")
    fig = go.Figure(go.Scatter(
        x=rows.nav_date, y=rows.t, mode="lines+markers",
        line=dict(color=BLUE, width=2.4), fill="tozeroy",
        fillcolor="rgba(37,99,235,0.12)"))
    fig.update_layout(**_BASE_LAYOUT, showlegend=False)
    fig.update_yaxes(title_text="total NAV (CAD millions)")
    return _div(fig)


def _fig_dq_trend() -> str:
    rows = db.query("SELECT run_date, AVG(pass_rate)*100 AS score "
                    "FROM dq_result GROUP BY run_date ORDER BY run_date")
    fig = go.Figure(go.Scatter(
        x=rows.run_date, y=rows.score, mode="lines+markers",
        line=dict(color=GREEN, width=2.4)))
    fig.update_layout(**_BASE_LAYOUT, showlegend=False)
    fig.update_yaxes(title_text="quality score (0-100)",
                     range=[max(0, float(rows.score.min()) - 5), 100])
    return _div(fig)


def _fig_nav_by_pool(as_of: str) -> str:
    rows = db.query(
        "SELECT p.pool_name, n.nav_cad/1e6 AS v FROM fact_nav n "
        "JOIN dim_pool p ON p.pool_id = n.pool_id "
        "WHERE n.nav_date=? ORDER BY v DESC", (as_of,))
    fig = go.Figure(go.Bar(
        x=rows.pool_name, y=rows.v, marker_color=BAR_PALETTE[:len(rows)],
        text=rows.v.round(1), textposition="auto"))
    fig.update_layout(**_BASE_LAYOUT, showlegend=False)
    fig.update_yaxes(title_text="NAV (CAD millions)")
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
            f"<td>{r.security_id}</td>"
            f"<td>{r.break_type.replace('_', ' ').title()}</td>"
            f"<td class='sev-{r.severity}'>{r.severity}</td>"
            f"<td class='num'>{r.mv_impact_cad:,.0f}</td>"
            f"<td>{(r.ai_root_cause or '').replace('_', ' ').title()}</td>"
            f"<td>{r.ai_owner_team or ''}</td></tr>")
    return "\n".join(body)


# ── narrative + KPI cards ────────────────────────────────────────────────────
def _narrative(as_of: str, score: float, total_nav: float,
               open_breaks: int, high_breaks: int, n_pools: int) -> str:
    dq_word = ("looks healthy" if score >= 95
               else "needs attention" if score >= 90 else "is poor")
    if open_breaks == 0:
        breaks_txt = ("No mismatches were found between our records and the "
                      "custodian's.")
    else:
        noun = "mismatch" if open_breaks == 1 else "mismatches"
        tail = (f", and <b>{high_breaks}</b> of them {'is' if high_breaks == 1 else 'are'} "
                f"high-impact and need same-day attention" if high_breaks
                else " &mdash; none are high-impact")
        breaks_txt = (f"<b>{open_breaks}</b> {noun} (“breaks”) were "
                      f"found between our records and the custodian's{tail}.")
    return (f"On <b>{as_of}</b>, the quality of the incoming data scored "
            f"<b>{score:.0f}/100</b> &mdash; it {dq_word}. {breaks_txt} "
            f"Total assets managed across the {n_pools} pools come to "
            f"<b>CAD {total_nav / 1e6:,.1f} million</b>.")


def _kpi_card(label: str, value: str, value_color: str, sub: str,
              pill: str = "", pill_color: str = "") -> str:
    pill_html = (f'<span class="pill" style="background:{pill_color}22;'
                 f'color:{pill_color}">{pill}</span>') if pill else ""
    return (f'<div class="card"><div class="card-top">'
            f'<span class="label">{label}</span>{pill_html}</div>'
            f'<div class="value" style="color:{value_color}">{value}</div>'
            f'<div class="sub">{sub}</div></div>')


# ── page template ────────────────────────────────────────────────────────────
_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>PoolDesk — Operations Dashboard</title>
<script>$plotlyjs</script>
<style>
 *{box-sizing:border-box;}
 body{margin:0;background:#f5f6f8;color:#1f2430;
   font-family:'Segoe UI',Arial,sans-serif;line-height:1.5;}
 .header{background:#1f2a44;color:#fff;padding:16px 28px;}
 .header h1{margin:0;font-size:19px;font-weight:600;}
 .header .sub{font-size:13px;color:#aab4cb;margin-top:3px;}
 .wrap{padding:18px 28px 8px;max-width:1280px;margin:0 auto;}
 .narrative{background:#fff;border-left:4px solid #2563EB;border-radius:8px;
   box-shadow:0 1px 4px rgba(0,0,0,.08);padding:14px 18px;margin-bottom:16px;
   font-size:14.5px;}
 .narrative .tag{font-size:11px;font-weight:700;letter-spacing:.6px;
   color:#2563EB;text-transform:uppercase;display:block;margin-bottom:4px;}
 .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;
   margin-bottom:16px;}
 .card{background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.08);
   padding:14px 16px;}
 .card-top{display:flex;justify-content:space-between;align-items:center;}
 .card .label{font-size:11px;color:#6b7280;text-transform:uppercase;
   letter-spacing:.5px;font-weight:600;}
 .pill{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:10px;}
 .card .value{font-size:31px;font-weight:700;margin:6px 0 2px;}
 .card .sub{font-size:12px;color:#6b7280;}
 .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;}
 .tile{background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.08);
   padding:12px 16px;}
 .tile.wide{grid-column:1 / -1;}
 .tile h3{margin:2px 0 1px;font-size:14px;font-weight:600;}
 .tile .cap{font-size:12px;color:#6b7280;font-style:italic;margin-bottom:4px;}
 table{width:100%;border-collapse:collapse;font-size:12.5px;}
 th{background:#f1f3f6;text-align:left;padding:8px 9px;color:#6b7280;
   font-weight:600;}
 td{padding:7px 9px;border-bottom:1px solid #edeff2;}
 td.num{text-align:right;font-variant-numeric:tabular-nums;}
 .sev-HIGH{color:#D64550;font-weight:700;}
 .sev-MEDIUM{color:#C77700;font-weight:700;}
 .sev-LOW{color:#1E9E5A;}
 .footer{padding:14px 28px 22px;font-size:11.5px;color:#9aa0ab;
   max-width:1280px;margin:0 auto;}
</style></head>
<body>
 <div class="header">
   <h1>PoolDesk &mdash; Investment Operations Dashboard</h1>
   <div class="sub">A daily snapshot of the operations pipeline:
     data health, reconciliation and fund values &middot; as of $as_of</div>
 </div>
 <div class="wrap">
   <div class="narrative"><span class="tag">Today in plain words</span>
     $narrative</div>
   <div class="kpis">$kpis</div>
   <div class="grid">
     <div class="tile"><h3>Breaks by severity</h3>
       <div class="cap">How serious the mismatches are &mdash; HIGH ones move
         large dollar amounts and are reviewed first.</div>$donut</div>
     <div class="tile"><h3>Breaks by type</h3>
       <div class="cap">What kind of mismatch &mdash; a wrong quantity, or a
         position only one side has.</div>$bartypes</div>
     <div class="tile"><h3>Total NAV trend</h3>
       <div class="cap">Total value of all pools over the month &mdash; it
         should move smoothly with the market.</div>$navtrend</div>
     <div class="tile"><h3>Data quality trend</h3>
       <div class="cap">Daily data-quality score &mdash; higher means cleaner
         data arrived that day.</div>$dqtrend</div>
     <div class="tile"><h3>NAV by pool</h3>
       <div class="cap">How the money is split across the five asset-class
         pools, as of $as_of.</div>$navpool</div>
     <div class="tile"><h3>Client holdings</h3>
       <div class="cap">Each client's stake by value &mdash; a bigger box is a
         bigger client.</div>$treemap</div>
     <div class="tile wide"><h3>Largest breaks needing review</h3>
       <div class="cap">The biggest mismatches by dollar impact, with the AI's
         suggested cause and the team that should resolve each.</div>
       <table><thead><tr><th>Run date</th><th>Pool</th><th>Security</th>
       <th>Break type</th><th>Severity</th><th>MV impact (CAD)</th>
       <th>AI root cause</th><th>Owner team</th></tr></thead>
       <tbody>$table</tbody></table></div>
   </div>
 </div>
 <div class="footer">Auto-generated by PoolDesk on each pipeline run &middot;
   learning portfolio simulation &middot; operational data is synthetic
   &middot; see docs/GUIDE.md for a plain-language explanation of every term.
 </div>
</body></html>
""")


def build_dashboard(out_path: Path | None = None) -> Path:
    """Build the self-contained, plain-language operations dashboard."""
    as_of = db.query("SELECT MAX(nav_date) AS d FROM fact_nav").d.iloc[0]
    if as_of is None:
        raise RuntimeError("no NAV data — run the pipeline before the dashboard")

    total_nav = float(db.query(
        "SELECT COALESCE(SUM(nav_cad),0) AS s FROM fact_nav WHERE nav_date=?",
        (as_of,)).s.iloc[0])
    n_pools = int(db.query(
        "SELECT COUNT(*) AS n FROM fact_nav WHERE nav_date=?",
        (as_of,)).n.iloc[0])
    score = data_quality.dq_scorecard(date.fromisoformat(as_of))["overall_score"]
    sev = dict(db.query(
        "SELECT severity, COUNT(*) AS n FROM recon_exception "
        "WHERE run_date=? AND status='OPEN' GROUP BY severity",
        (as_of,)).itertuples(index=False, name=None))
    open_breaks = sum(sev.values())
    high_breaks = sev.get("HIGH", 0)

    # KPI cards — each carries a status pill and a plain sub-label.
    dq_color, dq_pill = ((GREEN, "Healthy") if score >= 95
                         else (AMBER, "Watch") if score >= 90
                         else (RED, "Poor"))
    open_color, open_pill = ((GREEN, "Clear") if open_breaks == 0
                             else (AMBER, "Review"))
    high_color, high_pill = ((GREEN, "None") if high_breaks == 0
                             else (RED, "Act today"))
    kpis = "".join([
        _kpi_card("Data Quality Score", f"{score:.1f}", dq_color,
                  "% of data checks that passed", dq_pill, dq_color),
        _kpi_card("Total NAV", f"CAD {total_nav / 1e6:,.1f}M", BLUE,
                  f"value of all {n_pools} pools combined"),
        _kpi_card("Open Breaks", str(open_breaks), open_color,
                  "record mismatches awaiting review", open_pill, open_color),
        _kpi_card("High-Severity Breaks", str(high_breaks), high_color,
                  "large breaks — resolve same day", high_pill, high_color),
    ])

    html = _TEMPLATE.substitute(
        plotlyjs=get_plotlyjs(),
        as_of=as_of,
        narrative=_narrative(as_of, score, total_nav, open_breaks,
                             high_breaks, n_pools),
        kpis=kpis,
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
