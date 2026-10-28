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
    {"plan_id": plan_id, "plan_name": name, "line_of_business": lob, "payer_id": payer_id}
    for plan_id, name, lob, payer_id in [
        ("PLAN_MA1", "Synthetic Health Advantage", "MA", "SYNMA1"),
        ("PLAN_MA2", "Synthetic Health Advantage Plus", "MA", "SYNMA2"),
        ("PLAN_MCD", "Synthetic Health Medicaid", "MEDICAID", "SYNMCD"),
    ]
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


def fake_address(fake: Faker) -> dict:
    return {
        "address1": fake.street_address(),
        "city": fake.city(),
        "state": SERVICE_STATE,
        "zip": fake.zipcode_in_state(SERVICE_STATE),
    }


def vendor_address(fake: Faker) -> dict:
    """The 837 requires ZIP+4 for the billing provider (2010AA N403), so vendors get 9 digits."""
    address = fake_address(fake)
    address["zip"] += fake.numerify("####")
    return address


def make_members(config: Config, rng: random.Random, fake: Faker) -> list[dict]:
    window_start = config.trips_start_date
    window_end = config.run_date
    members = []
    for i in range(1, config.n_members + 1):
        plan_id = rng.choices([p["plan_id"] for p in PLANS], weights=[45, 25, 30])[0]
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

        members.append({
            "member_id": f"M{i:08d}",
            "plan_id": plan_id,
            "first_name": fake.first_name_female() if gender == "F" else fake.first_name_male(),
            "last_name": fake.last_name(),
            "birth_date": birth_date,
            "gender": gender,
            **fake_address(fake),
            "eligibility_start": eligibility_start,
            "eligibility_end": eligibility_end,
        })
    return members


def make_vendors(config: Config, rng: random.Random, fake: Faker) -> list[dict]:
    vendors = []
    for i in range(1, config.n_vendors + 1):
        vendors.append({
            "vendor_id": f"V{i:04d}",
            "vendor_name": f"{fake.last_name()} Transport LLC",
            "npi": fake_npi(rng),
            "tax_id": fake_tax_id(rng),
            **vendor_address(fake),
        })
    return vendors


# Origin/destination codes used in transport modifiers (origin letter + destination
# letter, so R then P gives modifier RP). Only the ones this project uses:
# R residence, P physician's office, H hospital, D diagnostic or therapeutic site,
# J free-standing dialysis facility.
FACILITY_TYPES = {"P": 20, "H": 5, "D": 6, "J": 4}  # how many fake facilities of each type


def make_trips(
    config: Config,
    rng: random.Random,
    fake: Faker,
    members: list[dict],
    vendors: list[dict],
) -> list[dict]:
    """Round trips: an outbound leg from home and a return leg the same day.

    Each leg is its own trip (and later its own encounter), which is how NEMT
    brokers usually count them.
    """
    facilities = {
        code: [fake_address(fake) for _ in range(count)]
        for code, count in FACILITY_TYPES.items()
    }
    vendor_ids = [v["vendor_id"] for v in vendors]
    last_trip_day = config.run_date - timedelta(days=1)

    # Per-member traits: how they ride and where they usually go.
    level_of_service = {}
    usual_destination = {}
    for m in members:
        level_of_service[m["member_id"]] = rng.choices(
            ["ambulatory", "wheelchair", "stretcher"], weights=[70, 22, 8]
        )[0]
        # Dialysis patients ride the most, always to the same clinic.
        usual_destination[m["member_id"]] = "J" if rng.random() < 0.08 else None
    ride_weights = [6 if usual_destination[m["member_id"]] == "J" else 1 for m in members]

    legs = []
    # At most one round trip per member per day. Two would look like duplicates to the
    # payer, and duplicates should only come from inject_problems.
    booked: set[tuple] = set()
    while len(legs) < config.n_trips:
        m = rng.choices(members, weights=ride_weights)[0]
        # Only schedule rides while the member is eligible; injected problems break this later.
        start = max(m["eligibility_start"], config.trips_start_date)
        end = min(m["eligibility_end"] or last_trip_day, last_trip_day)
        if start > end:
            continue
        home = {k: m[k] for k in ("address1", "city", "state", "zip")}
        trip_date = start + timedelta(days=rng.randint(0, (end - start).days))
        if (m["member_id"], trip_date) in booked:
            continue
        booked.add((m["member_id"], trip_date))
        dest_type = usual_destination[m["member_id"]] or rng.choices(
            ["P", "H", "D"], weights=[70, 15, 15]
        )[0]
        shared = {
            "member_id": m["member_id"],
            "trip_date": trip_date,
            "dest": rng.choice(facilities[dest_type]),
            "loaded_miles": round(rng.uniform(2, 40), 1),
            "vendor_id": rng.choice(vendor_ids),
            "level_of_service": level_of_service[m["member_id"]],
            # Both legs share a status: if the outbound ride didn't happen, the return
            # didn't either.
            "status": rng.choices(["completed", "cancelled", "no_show"], weights=[86, 9, 5])[0],
            "reported_date": trip_date + timedelta(days=report_lag(rng)),
        }
        legs.append(trip_leg(shared, "R", home, dest_type, shared["dest"]))
        legs.append(trip_leg(shared, dest_type, shared["dest"], "R", home))

    legs.sort(key=lambda leg: (leg["trip_date"], leg["member_id"]))  # stable: return stays 2nd
    legs = legs[: config.n_trips]
    for i, leg in enumerate(legs, start=1):
        leg["trip_id"] = f"T{i:08d}"
    return legs


def report_lag(rng: random.Random) -> int:
    """Days between the ride and the vendor confirming it. Most are quick; a few vendors
    batch their paperwork and report weeks late, which pushes those past the deadline."""
    bucket = rng.choices(["fast", "slow", "late"], weights=[85, 10, 5])[0]
    if bucket == "fast":
        return rng.randint(1, 5)
    if bucket == "slow":
        return rng.randint(6, 20)
    return rng.randint(21, 60)


def trip_leg(shared: dict, origin_type: str, origin: dict, dest_type: str, dest: dict) -> dict:
    return {
        "member_id": shared["member_id"],
        "vendor_id": shared["vendor_id"],
        "trip_date": shared["trip_date"],
        "origin_type": origin_type,
        **{f"pickup_{k}": v for k, v in origin.items()},
        "destination_type": dest_type,
        **{f"dropoff_{k}": v for k, v in dest.items()},
        "level_of_service": shared["level_of_service"],
        "loaded_miles": shared["loaded_miles"],
        "status": shared["status"],
        "reported_date": shared["reported_date"],
    }


# Deliberate data problems, each one tied to a rejection the payer will send back.
PROBLEMS = ["not_eligible", "missing_npi", "invalid_npi", "future_date", "duplicate", "bad_zip"]

# Two extra vendors exist only to carry the NPI problems. Moving a trip to one of them
# is how a trip ends up with a missing or bad NPI, while the real vendors stay clean.
MISSING_NPI_VENDOR = "V9001"
INVALID_NPI_VENDOR = "V9002"


def make_problem_vendors(rng: random.Random, fake: Faker) -> list[dict]:
    good_npi = fake_npi(rng)
    bad_check_digit = str((int(good_npi[9]) + 1) % 10)
    return [
        {"vendor_id": vendor_id, "vendor_name": f"{fake.last_name()} Transport LLC",
         "npi": npi, "tax_id": fake_tax_id(rng), **vendor_address(fake)}
        for vendor_id, npi in [
            (MISSING_NPI_VENDOR, None),
            (INVALID_NPI_VENDOR, good_npi[:9] + bad_check_digit),
        ]
    ]


def inject_problems(
    config: Config,
    rng: random.Random,
    members: list[dict],
    trips: list[dict],
) -> list[dict]:
    """Break about error_rate of the completed trips, spread evenly over PROBLEMS.

    Edits trips in place (and appends duplicates). Returns the answer key rows.
    """
    completed = [t for t in trips if t["status"] == "completed"]
    total = round(len(completed) * config.error_rate)
    counts = {p: total // len(PROBLEMS) for p in PROBLEMS}
    for p in PROBLEMS[: total % len(PROBLEMS)]:
        counts[p] += 1

    members_by_id = {m["member_id"]: m for m in members}
    last_trip_day = config.run_date - timedelta(days=1)
    used: set[str] = set()
    problems = []

    def pick(n: int, pool: list[dict]) -> list[dict]:
        chosen = rng.sample([t for t in pool if t["trip_id"] not in used], n)
        used.update(t["trip_id"] for t in chosen)
        return chosen

    # Ride happened outside the member's eligibility span (e.g. after they termed).
    # Only possible for members whose span starts or ends inside the trip window.
    def has_gap(t: dict) -> bool:
        m = members_by_id[t["member_id"]]
        return m["eligibility_end"] is not None or m["eligibility_start"] > config.trips_start_date

    for t in pick(counts["not_eligible"], [t for t in completed if has_gap(t)]):
        m = members_by_id[t["member_id"]]
        problems.append({"trip_id": t["trip_id"], "problem": "not_eligible",
                         "original_value": t["trip_date"].isoformat()})
        if m["eligibility_end"] is not None:
            first, last = m["eligibility_end"] + timedelta(days=1), last_trip_day
        else:
            first, last = config.trips_start_date, m["eligibility_start"] - timedelta(days=1)
        new_date = first + timedelta(days=rng.randint(0, (last - first).days))
        # The ride really happened on the new date, so it gets reported that much later too.
        t["reported_date"] += new_date - t["trip_date"]
        t["trip_date"] = new_date

    for problem, vendor_id in [("missing_npi", MISSING_NPI_VENDOR),
                               ("invalid_npi", INVALID_NPI_VENDOR)]:
        for t in pick(counts[problem], completed):
            problems.append({"trip_id": t["trip_id"], "problem": problem,
                             "original_value": t["vendor_id"]})
            t["vendor_id"] = vendor_id

    # Keyed with next year's date. Always lands after run_date, so it's "in the future".
    for t in pick(counts["future_date"], completed):
        problems.append({"trip_id": t["trip_id"], "problem": "future_date",
                         "original_value": t["trip_date"].isoformat()})
        t["trip_date"] = t["trip_date"] + timedelta(days=365)

    # Vendor sent the same ride twice. The copy gets its own trip_id; the original is clean.
    next_id = len(trips) + 1
    for t in pick(counts["duplicate"], completed):
        copy = {**t, "trip_id": f"T{next_id:08d}"}
        next_id += 1
        trips.append(copy)
        problems.append({"trip_id": copy["trip_id"], "problem": "duplicate",
                         "original_value": t["trip_id"]})

    # Dropped a digit from the pickup ZIP.
    for t in pick(counts["bad_zip"], completed):
        problems.append({"trip_id": t["trip_id"], "problem": "bad_zip",
                         "original_value": t["pickup_zip"]})
        t["pickup_zip"] = t["pickup_zip"][:4]

    return problems


def load(con: duckdb.DuckDBPyConnection, table: str, rows: list[dict]) -> None:
    """Replace a table's contents, so re-running generate is idempotent."""
    con.execute(f"DELETE FROM {table}")
    if rows:
        columns = list(rows[0])
        placeholders = ", ".join("?" * len(columns))
        con.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            [[row[c] for c in columns] for row in rows],
        )


def run(config: Config, con: duckdb.DuckDBPyConnection) -> None:
    rng = random.Random(config.seed)
    fake = Faker("en_US")
    fake.seed_instance(config.seed)

    load(con, "plans", PLANS)
    members = make_members(config, rng, fake)
    vendors = make_vendors(config, rng, fake)
    trips = make_trips(config, rng, fake, members, vendors)
    vendors += make_problem_vendors(rng, fake)
    problems = inject_problems(config, rng, members, trips)

    load(con, "members", members)
    load(con, "vendors", vendors)
    load(con, "trips", trips)
    load(con, "injected_problems", problems)
