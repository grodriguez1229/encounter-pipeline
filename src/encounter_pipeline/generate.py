"""Synthetic source data: plans, members, vendors and trips.

Everything comes from one seeded random generator, so the same seed gives the same data.
"""

import random
from datetime import date, timedelta

import duckdb
from faker import Faker

from encounter_pipeline.config import Config
from encounter_pipeline.npi import npi_check_digit

# Obviously fake plans. Payer IDs are made up and don't belong to any real payer.
PLANS = [
    ("PLAN_MA1", "Synthetic Health Advantage", "MA", "SYNMA1"),
    ("PLAN_MA2", "Synthetic Health Advantage Plus", "MA", "SYNMA2"),
    ("PLAN_MCD", "Synthetic Health Medicaid", "MEDICAID", "SYNMCD"),
]

# NEMT programs run within one state, so every address is in the same state.
SERVICE_STATE = "TX"


def fake_npi(rng: random.Random) -> str:
    """A 10-digit NPI with a valid check digit.

    Real NPIs start with 1 or 2, so starting with 9 keeps these from ever
    matching a real provider.
    """
    first_nine = "9" + "".join(str(rng.randint(0, 9)) for _ in range(8))
    return first_nine + str(npi_check_digit(first_nine))


def fake_tax_id(rng: random.Random) -> str:
    # EIN prefix 00 is never issued by the IRS.
    return "00" + "".join(str(rng.randint(0, 9)) for _ in range(7))


def make_members(config: Config, rng: random.Random, fake: Faker) -> list[tuple]:
    window_start = config.trips_start_date
    window_end = config.run_date
    members = []
    for i in range(1, config.n_members + 1):
        plan_id = rng.choices([p[0] for p in PLANS], weights=[45, 25, 30])[0]
        gender = rng.choices(["F", "M", "U"], weights=[54, 45, 1])[0]
        # Medicaid skews younger, MA is mostly 65+.
        if plan_id == "PLAN_MCD":
            age = rng.randint(18, 64)
        else:
            age = rng.randint(65, 95)
        birth_date = window_start - timedelta(days=age * 365 + rng.randint(0, 364))

        # Most members are eligible the whole window. Some join late or leave early,
        # which gives the "not eligible on trip date" problem something to work with.
        eligibility_start = date(2025, 1, 1)
        eligibility_end = None
        roll = rng.random()
        if roll < 0.10:
            eligibility_start = window_start + timedelta(days=rng.randint(15, 90))
        elif roll < 0.20:
            eligibility_end = window_end - timedelta(days=rng.randint(30, 120))

        first_name = fake.first_name_female() if gender == "F" else fake.first_name_male()
        members.append((
            f"M{i:08d}",
            plan_id,
            first_name,
            fake.last_name(),
            birth_date,
            gender,
            fake.street_address(),
            fake.city(),
            SERVICE_STATE,
            fake.zipcode_in_state(SERVICE_STATE),
            eligibility_start,
            eligibility_end,
        ))
    return members


def make_vendors(config: Config, rng: random.Random, fake: Faker) -> list[tuple]:
    vendors = []
    for i in range(1, config.n_vendors + 1):
        vendors.append((
            f"V{i:04d}",
            f"{fake.last_name()} Transport LLC",
            fake_npi(rng),
            fake_tax_id(rng),
            fake.street_address(),
            fake.city(),
            SERVICE_STATE,
            fake.zipcode_in_state(SERVICE_STATE),
        ))
    return vendors


def load(con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple]) -> None:
    """Replace a table's contents, so re-running generate is idempotent."""
    con.execute(f"DELETE FROM {table}")
    if rows:
        placeholders = ", ".join("?" * len(rows[0]))
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)


def run(config: Config, con: duckdb.DuckDBPyConnection) -> None:
    rng = random.Random(config.seed)
    fake = Faker("en_US")
    fake.seed_instance(config.seed)

    load(con, "plans", PLANS)
    load(con, "members", make_members(config, rng, fake))
    load(con, "vendors", make_vendors(config, rng, fake))
