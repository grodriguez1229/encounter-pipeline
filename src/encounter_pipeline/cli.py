"""Command line entry point: `encounters <step>`."""

import argparse
import shutil

from encounter_pipeline import build, generate, ingest, payer, report, resubmit
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

# Rounds of resubmit -> simulate -> ingest. Each round answers the last round's fixes;
# it normally settles in two or three, the cap just stops a loop that never would.
MAX_RESUBMIT_ROUNDS = 10


def run_step(step: str, config: Config) -> None:
    with connect(config) as con:
        STEP_FUNCTIONS[step](config, con)


def run_all(config: Config) -> None:
    # Start clean so a fresh run always gives the same result.
    shutil.rmtree(config.data_dir, ignore_errors=True)
    with connect(config) as con:
        for step in (generate, build, payer, ingest):
            step.run(config, con)
        for round_number in range(1, MAX_RESUBMIT_ROUNDS + 1):
            print(f"-- resubmit round {round_number}")
            if resubmit.run(config, con) == 0:
                break
            payer.run(config, con)
            ingest.run(config, con)
        report.run(config, con)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="encounters", description=__doc__)
    parser.add_argument("--seed", type=int, default=Config.seed)
    sub = parser.add_subparsers(dest="command", required=True)
    for step in STEP_FUNCTIONS:
        sub.add_parser(step)
    sub.add_parser("run-all", help="wipe data/ and run the whole pipeline")
    args = parser.parse_args(argv)

    config = Config(seed=args.seed)
    if args.command == "run-all":
        run_all(config)
    else:
        run_step(args.command, config)
