"""report: build the models and write the metrics as Markdown.

Prints a short summary and writes the full report to data/report.md.
"""

import duckdb

from encounter_pipeline.config import Config
from encounter_pipeline.models import build_models

SECTIONS = [
    ("Completeness by plan", """
        SELECT plan_id AS plan, completed_trips, accepted, awaiting_response, rejected_open,
               rejected_final, not_submitted, completeness_pct
        FROM metric_completeness WHERE trip_month IS NULL ORDER BY plan_id = 'All plans', plan_id
    """),
    # Trips dated after run_date are typos waiting on a fix, so they share one row.
    ("Completeness by trip month, all plans", """
        SELECT
            CASE WHEN trip_month > $run_date THEN 'future date (bad data)'
                 ELSE strftime(trip_month, '%Y-%m') END AS month,
            sum(completed_trips) AS completed_trips,
            sum(accepted) AS accepted,
            sum(not_submitted) AS not_submitted,
            round(100.0 * sum(accepted) / sum(completed_trips), 1) AS completeness_pct
        FROM metric_completeness
        WHERE plan_id = 'All plans' AND trip_month IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """),
    ("Accuracy", """
        SELECT plan_id AS plan, submitted, first_pass_accepted, first_pass_rejected_999,
               first_pass_rejected_277ca, first_pass_acceptance_pct, resubmitted,
               resubmitted_accepted, resubmit_success_pct
        FROM metric_accuracy ORDER BY plan_id = 'All plans', plan_id
    """),
    ("Rejections by reason", """
        SELECT response_type, status_code, status_description, rejections, trips
        FROM metric_rejection_reasons ORDER BY rejections DESC, status_code
    """),
    ("Timeliness (days from trip)", """
        SELECT plan_id AS plan, median_days_to_submit, p90_days_to_submit,
               median_days_to_accept, p90_days_to_accept, past_deadline, past_deadline_pct
        FROM metric_timeliness ORDER BY plan_id = 'All plans', plan_id
    """),
]


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def markdown_table(con: duckdb.DuckDBPyConnection, sql: str, config: Config) -> str:
    params = {"run_date": config.run_date} if "$run_date" in sql else {}
    cursor = con.execute(sql, params)
    header = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def summary(con: duckdb.DuckDBPyConnection, config: Config) -> list[str]:
    completeness = con.execute(
        "SELECT completeness_pct FROM metric_completeness "
        "WHERE plan_id = 'All plans' AND trip_month IS NULL").fetchone()[0]
    first_pass, resubmit = con.execute(
        "SELECT first_pass_acceptance_pct, resubmit_success_pct FROM metric_accuracy "
        "WHERE plan_id = 'All plans'").fetchone()
    median_submit, late_pct = con.execute(
        "SELECT median_days_to_submit, past_deadline_pct FROM metric_timeliness "
        "WHERE plan_id = 'All plans'").fetchone()
    return [
        f"- Completeness: {fmt(completeness)}% of completed trips have an accepted encounter",
        f"- First-pass acceptance: {fmt(first_pass)}%, resubmission success: {fmt(resubmit)}%",
        f"- Median days from trip to submission: {fmt(median_submit)}; "
        f"{fmt(late_pct)}% past the {config.submission_deadline_days}-day deadline",
    ]


def render(con: duckdb.DuckDBPyConnection, config: Config) -> str:
    parts = [f"# Encounter report, as of {config.run_date:%Y-%m-%d}", "",
             *summary(con, config)]
    for title, sql in SECTIONS:
        parts += ["", f"## {title}", "", markdown_table(con, sql, config)]
    return "\n".join(parts) + "\n"


def run(config: Config, con: duckdb.DuckDBPyConnection) -> None:
    build_models(con, {
        "run_date": config.run_date.isoformat(),
        "submission_deadline_days": config.submission_deadline_days,
    })
    path = config.data_dir / "report.md"
    path.write_text(render(con, config))
    print("\n".join(summary(con, config)))
    print(f"report: wrote {path}")
