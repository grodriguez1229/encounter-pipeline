from datetime import timedelta

import pytest

from encounter_pipeline import generate, resubmit
from encounter_pipeline.cli import run_nights
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.x12.read_837 import read_837

LATEST = """
    WITH latest AS (
        SELECT sc.trip_id, sc.submission_id
        FROM submission_claims sc JOIN submissions s USING (submission_id)
        QUALIFY row_number() OVER (
            PARTITION BY sc.trip_id ORDER BY s.created_at DESC, s.submission_id DESC) = 1
    )
    SELECT l.trip_id, h.status, h.received_at, p.problem
    FROM latest l
    LEFT JOIN claim_status_history h USING (trip_id, submission_id)
    LEFT JOIN injected_problems p USING (trip_id)
"""


@pytest.fixture(scope="module")
def cycled(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("resubmit")
    config = Config(data_dir=tmp / "data", n_members=200, n_trips=1200, error_rate=0.2)
    con = connect(config)
    generate.run(config, con)
    run_nights(config, con)
    return config, con


def test_final_rejections_are_only_eligibility_and_duplicates(cycled):
    _, con = cycled
    rows = con.execute("""
        SELECT f.status_codes, p.problem
        FROM final_rejections f LEFT JOIN injected_problems p USING (trip_id)
    """).fetchall()
    assert rows
    assert {(codes, problem) for codes, problem in rows} <= {
        ("A3:109:IL", "not_eligible"), ("A3:54", "duplicate"),
    }


def test_every_trip_ends_accepted_final_or_waiting(cycled):
    config, con = cycled
    finals = {t for (t,) in con.execute("SELECT trip_id FROM final_rejections").fetchall()}
    recent = config.run_date - timedelta(days=5)
    for trip_id, status, received_at, problem in con.execute(LATEST).fetchall():
        if status == "rejected" and trip_id not in finals:
            # Rejected recently enough that ops hasn't fixed it yet.
            assert received_at.date() >= recent, trip_id
        if problem == "duplicate":
            assert status != "accepted", f"duplicate {trip_id} accepted over its original"
        if problem in ("bad_zip", "invalid_npi", "missing_npi", "future_date") and \
                trip_id in finals:
            pytest.fail(f"{trip_id} ({problem}) was fixable but finalized")


def test_replacements_point_at_the_accepted_claim(cycled):
    config, con = cycled
    replacements = con.execute("""
        SELECT s.file_name, sc.trip_id, sc.payer_claim_number
        FROM submission_claims sc JOIN submissions s USING (submission_id)
        WHERE sc.frequency_code = '7'
    """).fetchall()
    assert replacements
    accepted_pcns = {
        (t, n) for t, n in con.execute(
            "SELECT trip_id, payer_claim_number FROM claim_status_history "
            "WHERE status = 'accepted'").fetchall()
    }
    for file_name, trip_id, pcn in replacements:
        assert (trip_id, pcn) in accepted_pcns
        claims = read_837((config.outbound_dir / file_name).read_text()).claims
        [claim] = [c for c in claims if c.trip_id == trip_id]
        assert (claim.frequency_code, claim.payer_claim_number) == ("7", pcn)


def test_rerun_without_new_responses_sends_nothing(cycled):
    config, con = cycled
    before = con.execute("SELECT count(*) FROM submissions").fetchone()[0]
    resubmit.run(config, con)
    assert con.execute("SELECT count(*) FROM submissions").fetchone()[0] == before


def test_vendor_fix_applies_to_every_file_built_after_it(cycled):
    _, con = cycled
    before, after = con.execute("""
        SELECT
            count(*) FILTER (WHERE s.created_at::DATE <= a.adjusted_on),
            count(*) FILTER (WHERE s.created_at::DATE > a.adjusted_on)
        FROM claim_status_history h
        JOIN submissions s USING (submission_id)
        JOIN trips t USING (trip_id)
        JOIN source_adjustments a ON a.table_name = 'vendors' AND a.row_id = t.vendor_id
        WHERE h.status = 'rejected' AND (h.source = '999' OR h.status_codes = 'A7:562:85')
    """).fetchone()
    assert before > 0
    assert after == 0
