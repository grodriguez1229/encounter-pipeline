import pytest

from encounter_pipeline import generate
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.npi import is_valid_npi

TABLES = ["plans", "members", "vendors", "trips", "injected_problems", "mileage_corrections"]


def snapshot(con):
    return {t: con.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in TABLES}


def test_same_seed_same_data_and_rerun_is_idempotent(tmp_path):
    config = Config(data_dir=tmp_path / "data", n_members=50, n_vendors=5, n_trips=200)
    with connect(config) as con:
        generate.run(config, con)
        first = snapshot(con)
        generate.run(config, con)
        assert snapshot(con) == first

    other = Config(data_dir=tmp_path / "other", n_members=50, n_vendors=5, n_trips=200)
    with connect(other) as con:
        generate.run(other, con)
        assert snapshot(con) == first


def test_vendor_npis_are_valid_and_fake(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    with connect(config) as con:
        generate.run(config, con)
        real = [r[0] for r in con.execute(
            "SELECT npi FROM vendors WHERE vendor_id NOT IN (?, ?)",
            [generate.MISSING_NPI_VENDOR, generate.INVALID_NPI_VENDOR],
        ).fetchall()]
    assert real and all(is_valid_npi(n) and n.startswith("9") for n in real)


def test_clean_trips_fall_inside_eligibility(tmp_path):
    config = Config(data_dir=tmp_path / "data", n_trips=500, error_rate=0)
    with connect(config) as con:
        generate.run(config, con)
        bad = con.execute("""
            SELECT count(*)
            FROM trips t JOIN members m USING (member_id)
            WHERE t.trip_date < m.eligibility_start
               OR t.trip_date > coalesce(m.eligibility_end, DATE '9999-12-31')
               OR t.trip_date >= ?
        """, [config.run_date]).fetchone()[0]
        count = con.execute("SELECT count(*) FROM trips").fetchone()[0]
    assert count == 500
    assert bad == 0


# For each problem, a query that returns the trips that actually have it.
PROBLEM_CHECKS = {
    "not_eligible": """
        SELECT trip_id FROM trips t JOIN members m USING (member_id)
        WHERE t.trip_date < m.eligibility_start OR t.trip_date > m.eligibility_end""",
    "missing_npi": "SELECT trip_id FROM trips JOIN vendors USING (vendor_id) WHERE npi IS NULL",
    "invalid_npi": """
        SELECT trip_id FROM trips JOIN vendors USING (vendor_id)
        WHERE vendor_id = 'V9002'""",
    "future_date": "SELECT trip_id FROM trips WHERE trip_date >= DATE '2026-06-30'",
    "duplicate": """
        SELECT trip_id FROM (
            SELECT trip_id, row_number() OVER (
                PARTITION BY member_id, trip_date, origin_type, destination_type ORDER BY trip_id
            ) AS n FROM trips)
        WHERE n > 1""",
    "bad_zip": "SELECT trip_id FROM trips WHERE length(pickup_zip) <> 5",
}


def test_injected_problems_match_the_answer_key(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    with connect(config) as con:
        generate.run(config, con)
        completed = con.execute(
            "SELECT count(*) FROM trips WHERE status = 'completed'"
        ).fetchone()[0]
        key = con.execute("SELECT problem, trip_id FROM injected_problems").fetchall()
        assert {p for p, _ in key} == set(generate.PROBLEMS)
        assert len(key) == pytest.approx(completed * config.error_rate, rel=0.05)
        all_broken = {t for _, t in key}
        for problem, sql in PROBLEM_CHECKS.items():
            found = {r[0] for r in con.execute(sql).fetchall()}
            expected = {t for p, t in key if p == problem}
            # Every trip we broke shows the problem, and no clean trip does. Overlap
            # between problems is fine: a future date can also fall after eligibility ends.
            assert expected <= found <= all_broken, problem

    with connect(config) as con:
        assert not is_valid_npi(con.execute(
            "SELECT npi FROM vendors WHERE vendor_id = 'V9002'").fetchone()[0])
