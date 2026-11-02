"""The pipeline as an Airflow DAG: one task per step, calling the same functions as the CLI.

Not run in tests or CI, just a sketch of how it would be scheduled. Each task opens its
own DuckDB connection, and the tasks run one at a time, so the file lock is never fought
over. The data folder comes from ENCOUNTERS_DATA_DIR because a worker's working
directory isn't the repo.

Unlike `run-all`, this doesn't wipe data/ first: a scheduled run picks up where the last
one stopped (build only sends unsent trips, ingest skips loaded files).
"""

import os
from datetime import datetime
from pathlib import Path

from airflow.sdk import chain, dag, task

from encounter_pipeline.cli import run_step
from encounter_pipeline.config import Config

# Airflow wants a fixed graph, so the resubmit loop is a fixed number of rounds instead
# of "until nothing goes out". Extra rounds are cheap no-ops: resubmit sends nothing,
# simulate has no new files to answer, ingest has nothing new to load.
RESUBMIT_ROUNDS = 3


def config() -> Config:
    return Config(data_dir=Path(os.environ.get("ENCOUNTERS_DATA_DIR", "data")))


def step_task(step: str, task_id: str | None = None):
    @task(task_id=task_id or step)
    def run() -> None:
        run_step(step, config())

    return run()


@dag(
    dag_id="encounters",
    schedule=None,  # would be "0 2 * * *" (the nightly 837P batch) against a real feed
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["x12", "encounters"],
)
def encounters():
    steps = [step_task("generate"), step_task("build"), step_task("simulate"),
             step_task("ingest")]
    for n in range(1, RESUBMIT_ROUNDS + 1):
        steps += [step_task("resubmit", f"resubmit_{n}"), step_task("simulate", f"simulate_{n}"),
                  step_task("ingest", f"ingest_{n}")]
    steps.append(step_task("report"))
    chain(*steps)


encounters()
