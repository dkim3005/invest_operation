"""PoolDesk — pipeline orchestrator (CLI).

Commands
--------
    python main.py generate              Build reference data + SIM_DAYS feeds
    python main.py init-db               Create the schema and load reference
    python main.py run --date YYYY-MM-DD Run one business day end to end
    python main.py run-all               Run every business day in order
    python main.py report --date ...     Rebuild a day's Excel/PDF reports
    python main.py rollup --week  YYYY-MM-DD
    python main.py rollup --month YYYY-MM

The per-day pipeline is: ingest -> data quality -> reconcile -> NAV ->
AI triage -> reporting. Each step's start, duration and outcome are logged
to the console and to reports/pipeline.log. See BUILD_SPEC.md Module 8.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date

import config
from pooldesk import (ai_assistant, data_generator, data_quality, db, ingest,
                      nav, reconcile, reporting)


def _setup_logging() -> logging.Logger:
    """Console + file logger — the pipeline's monitoring surface."""
    config.ensure_dirs()
    logger = logging.getLogger("pooldesk")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
        for handler in (logging.StreamHandler(sys.stdout),
                        logging.FileHandler(config.REPORTS_DIR /
                                            "pipeline.log")):
            handler.setFormatter(fmt)
            logger.addHandler(handler)
    return logger


def _run_day(log: logging.Logger, run_date: date) -> dict:
    """Run the full per-day pipeline, timing and logging each step."""
    steps = [
        ("ingest",       lambda: ingest.load_feed_day(run_date)),
        ("data_quality", lambda: data_quality.run_all_checks(run_date)),
        ("reconcile",    lambda: reconcile.write_exceptions(run_date)),
        ("nav",          lambda: (nav.compute_nav(run_date),
                                  nav.compute_client_holdings(run_date))),
        ("ai_assistant", lambda: ai_assistant.analyze_exceptions(run_date)),
        ("reporting",    lambda: (reporting.build_daily_excel(run_date),
                                  reporting.build_daily_pdf(run_date))),
    ]
    log.info("=== pipeline run for %s ===", run_date)
    for name, fn in steps:
        started = time.perf_counter()
        try:
            fn()
        except Exception:                              # error logging
            log.exception("step '%s' FAILED for %s", name, run_date)
            raise
        log.info("  step %-13s done in %5.2fs", name,
                 time.perf_counter() - started)

    scorecard = data_quality.dq_scorecard(run_date)
    diso = run_date.isoformat()
    breaks = int(db.query("SELECT COUNT(*) AS n FROM recon_exception "
                          "WHERE run_date=?", (diso,)).n.iloc[0])
    total_nav = float(db.query("SELECT COALESCE(SUM(nav_cad),0) AS s "
                               "FROM fact_nav WHERE nav_date=?",
                               (diso,)).s.iloc[0])
    log.info("  summary: DQ score %.1f | %d break(s) | NAV CAD %s",
             scorecard["overall_score"], breaks, format(total_nav, ",.0f"))
    return {"date": diso, "dq_score": scorecard["overall_score"],
            "breaks": breaks, "total_nav": total_nav}


def cmd_generate(log: logging.Logger) -> None:
    log.info("generating reference data and %d days of feeds", config.SIM_DAYS)
    data_generator.generate_all()


def cmd_init_db(log: logging.Logger) -> None:
    ingest.init_db()
    ingest.load_reference()
    log.info("database initialised and reference data loaded")


def cmd_run(log: logging.Logger, run_date: date) -> None:
    cmd_init_db(log)                      # idempotent — safe to ensure
    days = config.business_days(config.SIM_START_DATE, config.SIM_DAYS)
    if run_date not in days:
        log.error("date %s is outside the simulation window (%s .. %s)",
                  run_date, days[0], days[-1])
        sys.exit(2)
    # NAV fee accrual and daily P&L depend on the prior day's NAV — process
    # any earlier day that has not been run yet so the chain stays intact.
    for day in days:
        if day >= run_date:
            break
        done = db.query("SELECT COUNT(*) AS n FROM fact_nav WHERE nav_date=?",
                        (day.isoformat(),)).n.iloc[0]
        if not done:
            log.info("processing prerequisite day %s (NAV chain)", day)
            _run_day(log, day)
    _run_day(log, run_date)


def cmd_run_all(log: logging.Logger) -> None:
    cmd_init_db(log)
    days = config.business_days(config.SIM_START_DATE, config.SIM_DAYS)
    started = time.perf_counter()
    results = [_run_day(log, day) for day in days]      # in order: NAV chains
    elapsed = time.perf_counter() - started
    total_breaks = sum(r["breaks"] for r in results)
    avg_dq = sum(r["dq_score"] for r in results) / len(results)
    log.info("=== run-all complete: %d day(s) in %.1fs | %d break(s) | "
             "avg DQ %.1f ===", len(days), elapsed, total_breaks, avg_dq)
    reporting.export_for_powerbi()        # refresh CSVs for Power BI / Excel


def cmd_report(log: logging.Logger, run_date: date) -> None:
    xlsx = reporting.build_daily_excel(run_date)
    pdf = reporting.build_daily_pdf(run_date)
    log.info("rebuilt reports for %s: %s, %s", run_date, xlsx.name, pdf.name)


def cmd_rollup(log: logging.Logger, week: str | None,
               month: str | None) -> None:
    if week:
        path = reporting.build_weekly_rollup(date.fromisoformat(week))
        log.info("weekly roll-up written: %s", path)
    elif month:
        year, mon = (int(x) for x in month.split("-"))
        path = reporting.build_monthly_rollup(date(year, mon, 1))
        log.info("monthly roll-up written: %s", path)
    else:
        log.error("rollup needs --week YYYY-MM-DD or --month YYYY-MM")
        sys.exit(2)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="main.py",
                                     description="PoolDesk pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="build reference data + feeds")
    sub.add_parser("init-db", help="create schema and load reference data")
    run_p = sub.add_parser("run", help="run one business day")
    run_p.add_argument("--date", required=True, help="YYYY-MM-DD")
    sub.add_parser("run-all", help="run every business day")
    sub.add_parser("export", help="export analytical tables to CSV "
                                  "(Power BI / Excel)")
    rep_p = sub.add_parser("report", help="rebuild a day's reports")
    rep_p.add_argument("--date", required=True, help="YYYY-MM-DD")
    roll_p = sub.add_parser("rollup", help="build a weekly/monthly roll-up")
    roll_p.add_argument("--week", help="week-ending date, YYYY-MM-DD")
    roll_p.add_argument("--month", help="month, YYYY-MM")

    args = parser.parse_args(argv)
    log = _setup_logging()

    if args.command == "generate":
        cmd_generate(log)
    elif args.command == "init-db":
        cmd_init_db(log)
    elif args.command == "run":
        cmd_run(log, date.fromisoformat(args.date))
    elif args.command == "run-all":
        cmd_run_all(log)
    elif args.command == "export":
        reporting.export_for_powerbi()
    elif args.command == "report":
        cmd_report(log, date.fromisoformat(args.date))
    elif args.command == "rollup":
        cmd_rollup(log, args.week, args.month)


if __name__ == "__main__":
    main()
