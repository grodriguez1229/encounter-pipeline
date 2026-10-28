import shutil
from pathlib import Path

from encounter_pipeline import build, generate, ingest, payer
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect

FIXTURES = Path(__file__).parent / "fixtures"


def run_through_ingest(tmp_path):
    config = Config(data_dir=tmp_path / "data", n_members=150, n_trips=800, error_rate=0.2)
    con = connect(config)
    for step in (generate, build, payer, ingest):
        step.run(config, con)
    return config, con


def test_every_response_matches_and_nothing_is_quarantined(tmp_path):
    config, con = run_through_ingest(tmp_path)
    q = con.execute
    assert q("SELECT count(*) FROM quarantine").fetchone()[0] == 0
    files = q("SELECT count(*) FROM response_files").fetchone()[0]
    assert files == len(list(config.inbound_dir.iterdir()))

    # One 999 per submission, except ones whose 999 hasn't arrived yet (none in practice).
    assert q("SELECT count(*) FROM submission_acks").fetchone()[0] == \
        q("SELECT count(*) FROM submissions").fetchone()[0]

    # Each claim in a 999-rejected file gets a rejected row; each claim in an
    # arrived 277CA gets one row; nobody gets both from the same submission.
    both = q("""
        SELECT count(*) FROM (
            SELECT trip_id, submission_id FROM claim_status_history
            GROUP BY ALL HAVING count(DISTINCT source) > 1)
    """).fetchone()[0]
    assert both == 0

    # Accepted claims carry a payer claim number; rejected ones don't.
    bad = q("""
        SELECT count(*) FROM claim_status_history
        WHERE source = '277CA'
          AND (status = 'accepted') <> (payer_claim_number IS NOT NULL)
    """).fetchone()[0]
    assert bad == 0


def test_rerun_loads_nothing_new(tmp_path):
    config, con = run_through_ingest(tmp_path)
    before = con.execute("SELECT count(*) FROM claim_status_history").fetchone()[0]
    ingest.run(config, con)
    assert con.execute("SELECT count(*) FROM claim_status_history").fetchone()[0] == before


def test_unmatched_responses_go_to_quarantine(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    with connect(config) as con:
        # The golden files point at control numbers we never sent.
        for name in ("golden_999.x12", "golden_277ca.x12"):
            shutil.copy(FIXTURES / name, config.inbound_dir / name)
        ingest.run(config, con)
        reasons = sorted(r[0] for r in con.execute("SELECT reason FROM quarantine").fetchall())
        assert reasons == [
            "277CA: no submission with this batch ID",
            "999: no submission with this GS06/ST02",
            "999: no submission with this GS06/ST02",
        ]
        assert con.execute("SELECT count(*) FROM response_files").fetchone()[0] == 2
