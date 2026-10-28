from encounter_pipeline import build, generate
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect


def run_build(tmp_path, **overrides):
    config = Config(data_dir=tmp_path / "data", n_members=100, n_trips=400, **overrides)
    con = connect(config)
    generate.run(config, con)
    build.run(config, con)
    return config, con


def test_every_reported_completed_trip_is_submitted_once(tmp_path):
    config, con = run_build(tmp_path)
    missing, doubled = con.execute("""
        SELECT
            count(*) FILTER (WHERE n = 0),
            count(*) FILTER (WHERE n > 1)
        FROM (
            SELECT t.trip_id, count(sc.trip_id) AS n
            FROM trips t LEFT JOIN submission_claims sc USING (trip_id)
            WHERE t.status = 'completed' AND t.reported_date < ?
            GROUP BY t.trip_id
        )
    """, [config.run_date]).fetchone()
    assert (missing, doubled) == (0, 0)
    not_completed = con.execute("""
        SELECT count(*) FROM submission_claims JOIN trips USING (trip_id)
        WHERE status <> 'completed'
    """).fetchone()[0]
    assert not_completed == 0


def test_files_match_submissions_and_respect_max_claims(tmp_path):
    config, con = run_build(tmp_path, max_claims_per_file=3)
    rows = con.execute("SELECT file_name, claim_count, isa13 FROM submissions").fetchall()
    assert rows and max(r[1] for r in rows) <= 3
    for file_name, claim_count, isa13 in rows:
        text = (config.outbound_dir / file_name).read_text()
        assert text.count("CLM*") == claim_count
        assert f"*{isa13:09d}*0*T*:" in text


def test_rerun_submits_nothing_new(tmp_path):
    config, con = run_build(tmp_path)
    before = con.execute("SELECT count(*) FROM submissions").fetchone()[0]
    build.run(config, con)
    assert con.execute("SELECT count(*) FROM submissions").fetchone()[0] == before
