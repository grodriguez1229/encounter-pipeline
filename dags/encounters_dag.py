"""The nightly run as an Airflow DAG: one DAG run per night, one task per step.

Each run does what run-all does for a single night, calling the same functions:
collect the responses that came in, load them, send tonight's fixes, then send the
trips reported yesterday, and refresh the report. With catchup on, Airflow replays
every night from the first trip through run_date in order, which is run-all's loop.
The one difference: run-all also picks up responses that land later on run_date, after
the last nightly run; here those wait for the next night.

Not run in tests or CI. Run `encounters generate` once first; the DAG doesn't make
data. Tasks run one at a time (max_active_runs=1, one chain), so the DuckDB file
lock is never fought over. The data folder comes from ENCOUNTERS_DATA_DIR because a
worker's working directory isn't the repo.
"""

import os
from datetime import datetime
from pathlib import Path

from airflow.sdk import chain, dag, task

from encounter_pipeline import build, ingest, payer, report, resubmit
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect

CONFIG = Config(data_dir=Path(os.environ.get("ENCOUNTERS_DATA_DIR", "data")))


def tonight(logical_date: datetime) -> datetime:
    """The nightly run this DAG run stands for, as a plain local datetime."""
    return build.night_of(logical_date.date())


@dag(
    dag_id="encounters",
    schedule="0 2 * * *",
    start_date=datetime(2026, 1, 2),
    end_date=datetime.combine(CONFIG.run_date, build.NIGHTLY_RUN_TIME),
    catchup=True,
    max_active_runs=1,
    tags=["x12", "encounters"],
)
def encounters():
    @task
    def simulate(logical_date=None):
        # The payer starts fresh each night and replays every file sent so far.
        with connect(CONFIG) as con:
            return payer.run(CONFIG, con, tonight(logical_date))

    @task(task_id="ingest")
    def ingest_responses():
        with connect(CONFIG) as con:
            return ingest.run(CONFIG, con)

    @task(task_id="resubmit")
    def resubmit_fixes(logical_date=None):
        with connect(CONFIG) as con:
            return resubmit.run(CONFIG, con, tonight(logical_date))

    @task(task_id="build")
    def build_new_trips(logical_date=None):
        with connect(CONFIG) as con:
            return build.run(CONFIG, con, tonight(logical_date))

    @task(task_id="report")
    def refresh_report():
        with connect(CONFIG) as con:
            report.run(CONFIG, con)

    chain(simulate(), ingest_responses(), resubmit_fixes(), build_new_trips(), refresh_report())


encounters()
