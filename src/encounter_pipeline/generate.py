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


# Origin/destination codes used in transport modifiers (origin letter + destination
# letter, so R then P gives modifier RP). Only the ones this project uses:
# R residence, P physician's office, H hospital, D diagnostic or therapeutic site,
# J free-standing dialysis facility.
FACILITY_TYPES = {"P": 20, "H": 5, "D": 6, "J": 4}  # how many fake facilities of each type


def make_facilities(rng: random.Random, fake: Faker) -> dict[str, list[tuple]]:
    """Fake destinations by type, as (address1, city, state, zip)."""
    return {
        code: [
            (fake.street_address(), fake.city(), SERVICE_STATE,
             fake.zipcode_in_state(SERVICE_STATE))
            for _ in range(count)
        ]
        for code, count in FACILITY_TYPES.items()
    }


def make_trips(
    config: Config,
    rng: random.Random,
    fake: Faker,
    members: list[tuple],
    vendors: list[tuple],
) -> list[tuple]:
    """Round trips: an outbound leg from home and a return leg the same day.

    Each leg is its own trip (and later its own encounter), which is how NEMT
    brokers usually count them.
    """
    facilities = make_facilities(rng, fake)
    vendor_ids = [v[0] for v in vendors]
    last_trip_day = config.run_date - timedelta(days=1)

    # Per-member traits: how they ride and where they usually go.
    level_of_service = {}
    usual_destination = {}
    for m in members:
        level_of_service[m[0]] = rng.choices(
            ["ambulatory", "wheelchair", "stretcher"], weights=[70, 22, 8]
        )[0]
        # Dialysis patients ride the most, always to the same clinic.
        usual_destination[m[0]] = "J" if rng.random() < 0.08 else None
    ride_weights = [6 if usual_destination[m[0]] == "J" else 1 for m in members]

    legs = []
    while len(legs) < config.n_trips:
        m = rng.choices(members, weights=ride_weights)[0]
        member_id, home = m[0], (m[6], m[7], m[8], m[9])
        # Only schedule rides while the member is eligible; injected problems break this later.
        start = max(m[10], config.trips_start_date)
        end = min(m[11] or last_trip_day, last_trip_day)
        if start > end:
            continue
        trip_date = start + timedelta(days=rng.randint(0, (end - start).days))

        dest_type = usual_destination[member_id] or rng.choices(
            ["P", "H", "D"], weights=[70, 15, 15]
        )[0]
        dest = rng.choice(facilities[dest_type])
        miles = round(rng.uniform(2, 40), 1)
        vendor_id = rng.choice(vendor_ids)
        los = level_of_service[member_id]

        # Both legs share a status: if the outbound ride didn't happen, the return didn't either.
        status = rng.choices(["completed", "cancelled", "no_show"], weights=[86, 9, 5])[0]
        legs.append((member_id, vendor_id, trip_date, "R", home, dest_type, dest, los, miles,
                     status))
        legs.append((member_id, vendor_id, trip_date, dest_type, dest, "R", home, los, miles,
                     status))

    legs.sort(key=lambda leg: (leg[2], leg[0]))  # stable, so the return leg stays second
    trips = []
    for i, (member_id, vendor_id, trip_date, o_type, o_addr, d_type, d_addr, los, miles,
            status) in enumerate(legs[: config.n_trips], start=1):
        trips.append((f"T{i:08d}", member_id, vendor_id, trip_date, o_type, *o_addr,
                      d_type, *d_addr, los, miles, status))
    return trips


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
    members = make_members(config, rng, fake)
    vendors = make_vendors(config, rng, fake)
    load(con, "members", members)
    load(con, "vendors", vendors)
    load(con, "trips", make_trips(config, rng, fake, members, vendors))
