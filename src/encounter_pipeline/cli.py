"""Command line entry point: `encounters <step>`."""

import argparse
import shutil
from collections import Counter
from datetime import timedelta

import duckdb

from encounter_pipeline import build, generate, ingest, payer, report, resubmit, trip
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect

STEP_FUNCTIONS = {
    "generate": generate.run,
    "build": build.run,
    "simulate": payer.run,
    "ingest": ingest.run,
    "resubmit": resubmit.run,
    "report": report.run,
}

# What the steps that return a file count print.
COUNT_MESSAGES = {
    "build": "wrote {} 837P files",
    "simulate": "wrote {} response files",
    "ingest": "loaded {} response files",
    "resubmit": "wrote {} 837P files",
}


def run_step(step: str, config: Config) -> None:
    """One step on its own, as of the nightly run on run_date."""
    with connect(config) as con:
        result = STEP_FUNCTIONS[step](config, con)
    if step in COUNT_MESSAGES:
        print(f"{step}: {COUNT_MESSAGES[step].format(result)}")


def run_nights(config: Config, con: duckdb.DuckDBPyConnection) -> None:
    """Every nightly run from the first trip through run_date, in order.

    Each night: pick up the responses that came in since last night, work the
    rejections (fixes ops finished go out tonight), then send the trips reported
    yesterday. Fixes come before new trips so tonight's files use them.
    """
    sim = payer.Payer(config, con)
    months: dict[str, Counter] = {}
    day = config.trips_start_date + timedelta(days=1)
    while day <= config.run_date:
        now = build.night_of(day)
        counts = months.setdefault(f"{day:%Y-%m}", Counter())
        counts["responses"] += sim.deliver(now)
        ingest.run(config, con)
        counts["resubmission files"] += resubmit.run(config, con, now)
        counts["new files"] += build.run(config, con, now)
        day += timedelta(days=1)
    # Responses that land after the last nightly run, through the end of run_date.
    months[f"{config.run_date:%Y-%m}"]["responses"] += sim.deliver(payer.end_of(config.run_date))
    ingest.run(config, con)

    for month, counts in months.items():
        print(f"{month}: sent {counts['new files']} new files and "
              f"{counts['resubmission files']} resubmission files, "
              f"got {counts['responses']} responses")


def run_all(config: Config) -> None:
    # Start clean so a fresh run always gives the same result.
    shutil.rmtree(config.data_dir, ignore_errors=True)
    with connect(config) as con:
        generate.run(config, con)
        run_nights(config, con)
        finals = con.execute("SELECT count(*) FROM final_rejections").fetchone()[0]
        print(f"final rejections: {finals}")
        report.run(config, con)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="encounters", description=__doc__)
    parser.add_argument("--seed", type=int, default=Config.seed)
    sub = parser.add_subparsers(dest="command", required=True)
    for step in STEP_FUNCTIONS:
        sub.add_parser(step)
    sub.add_parser("run-all", help="wipe data/ and run every night through run_date")
    sub.add_parser("trip", help="show one trip's files, responses and fixes").add_argument(
        "trip_id")
    args = parser.parse_args(argv)

    config = Config(seed=args.seed)
    if args.command == "run-all":
        run_all(config)
    elif args.command == "trip":
        with connect(config) as con:
            trip.run(config, con, args.trip_id)
    else:
        run_step(args.command, config)
