"""Command line entry point: `encounters <step>`."""

import argparse
import shutil

from encounter_pipeline.config import Config

STEPS = ["generate", "build", "simulate", "ingest", "resubmit", "report"]


def run_step(step: str, config: Config) -> None:
    raise NotImplementedError(f"'{step}' isn't built yet")


def run_all(config: Config) -> None:
    # Start clean so a fresh run always gives the same result.
    shutil.rmtree(config.data_dir, ignore_errors=True)
    for step in STEPS:
        run_step(step, config)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="encounters", description=__doc__)
    parser.add_argument("--seed", type=int, default=Config.seed)
    sub = parser.add_subparsers(dest="command", required=True)
    for step in STEPS:
        sub.add_parser(step)
    sub.add_parser("run-all", help="wipe data/ and run every step in order")
    args = parser.parse_args(argv)

    config = Config(seed=args.seed)
    if args.command == "run-all":
        run_all(config)
    else:
        run_step(args.command, config)
